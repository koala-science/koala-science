"""The LLM proxy: agents call Gemini with their Koala key, paid from their
owner's model credit, and the server's key never leaves the server.

A drop-in base URL for Gemini clients: ``base_url`` for the ``google-genai``
SDK and ADK, or the same paths over REST. Runs as its own process so that
minutes-long model calls never hold the main API's workers.

Each billed call reserves its worst case under a lock on the owner's row, calls
Google without holding a database connection, then settles at what Google
reports and refunds the rest.
"""
import json
import logging
import uuid
from dataclasses import dataclass

import anyio
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import resolve_api_key_actor
from app.db.session import AsyncSessionLocal
from app.llm_proxy.registry import (
    MODELS,
    ModelPrice,
    RequestRejected,
    clamp,
    encode,
    reservation,
    usage_cost,
)
from app.models.identity import HumanAccount
from app.models.platform import ModelUsage

logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

session_factory = AsyncSessionLocal
rate_limiter = MovingWindowRateLimiter(storage_from_string(settings.REDIS_URL))
RATE_LIMIT = parse("60/minute")

BILLED_METHODS = {"generateContent", "streamGenerateContent"}
FREE_METHODS = {"countTokens"}
UPSTREAM_TIMEOUT = httpx.Timeout(300.0, connect=10.0)

STATUS_NAMES = {
    400: "INVALID_ARGUMENT",
    401: "UNAUTHENTICATED",
    402: "RESOURCE_EXHAUSTED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    429: "RESOURCE_EXHAUSTED",
    502: "UNAVAILABLE",
}

UNREACHABLE = "Could not reach Gemini; nothing was charged"


class ProxyError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Held:
    """A reservation taken against an owner's credit, recorded as a ledger row."""

    usage_id: uuid.UUID
    owner_id: uuid.UUID
    amount: int
    price: ModelPrice


@dataclass
class UpstreamStream:
    client: httpx.AsyncClient
    response: httpx.Response

    async def aclose(self) -> None:
        # Shielded: a client disconnect cancels the relaying task, and anyio
        # keeps cancelling every await in its scope, so an unshielded close
        # would be abandoned halfway and leak the upstream connection.
        with anyio.CancelScope(shield=True):
            await self.response.aclose()
            await self.client.aclose()


def upstream_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.GEMINI_UPSTREAM_URL, timeout=UPSTREAM_TIMEOUT)


def _upstream_headers() -> dict:
    return {"x-goog-api-key": settings.GEMINI_API_KEY, "content-type": "application/json"}


def _error(code: int, message: str) -> JSONResponse:
    """Shaped like Google's own errors, so Gemini clients show the message."""
    return JSONResponse(
        status_code=code,
        content={"error": {"code": code, "message": message, "status": STATUS_NAMES[code]}},
    )


def _client_key(request: Request) -> str | None:
    """Gemini clients send their key as ``x-goog-api-key`` or ``?key=``; others
    as a bearer token."""
    authorization = request.headers.get("authorization", "")
    bearer = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else None
    return request.headers.get("x-goog-api-key") or request.query_params.get("key") or bearer


async def authenticate(key: str | None) -> tuple[uuid.UUID, uuid.UUID]:
    """The agent behind a Koala API key, and its owner."""
    if key is None:
        raise ProxyError(401, "Missing API key: use your Koala agent key (cs_...)")
    if not key.startswith("cs_"):
        raise ProxyError(403, "Only Koala agent keys (cs_...) can use the model proxy")
    async with session_factory() as db:
        try:
            agent = await resolve_api_key_actor(key, db)
        except HTTPException as exc:
            raise ProxyError(exc.status_code, exc.detail) from exc
        return agent.id, agent.owner_id


async def _lock_owner(db, owner_id: uuid.UUID) -> HumanAccount:
    return (
        await db.execute(
            select(HumanAccount)
            .where(HumanAccount.id == owner_id)
            .with_for_update(of=HumanAccount.__table__)
        )
    ).scalar_one()


async def reserve(
    owner_id: uuid.UUID, agent_id: uuid.UUID, model: str, method: str, body: dict
) -> Held:
    """Take the call's worst case from the owner's credit, or refuse it.

    Under the owner's row lock, so sibling agents cannot both spend the last of it.
    """
    price = MODELS[model]
    amount = reservation(price, body)
    async with session_factory() as db:
        owner = await _lock_owner(db, owner_id)
        if owner.model_credit_microusd < amount:
            raise ProxyError(
                402,
                f"Not enough model credit: this call may cost up to ${amount / 1_000_000:.4f} "
                f"and ${owner.model_credit_microusd / 1_000_000:.4f} is left",
            )
        owner.model_credit_microusd -= amount
        usage = ModelUsage(
            owner_id=owner_id,
            agent_id=agent_id,
            model=model,
            method=method,
            status="reserved",
            reserved_microusd=amount,
            cost_microusd=amount,
        )
        db.add(usage)
        await db.commit()
        return Held(usage_id=usage.id, owner_id=owner_id, amount=amount, price=price)


async def settle(held: Held, usage: dict | None, upstream_status: int) -> None:
    """Charge what the call cost and refund the rest of its reservation.

    A failed call costs nothing. A successful one without usage figures keeps
    the whole reservation, since Google may have billed it.
    """
    async with session_factory() as db:
        owner = await _lock_owner(db, held.owner_id)
        row = await db.get(ModelUsage, held.usage_id)
        row.upstream_status = upstream_status
        if upstream_status >= 400:
            row.status, cost = "upstream_error", 0
        elif usage is None:
            row.status, cost = "unmetered", held.amount
        else:
            row.status, cost = "settled", usage_cost(held.price, usage)
            row.prompt_tokens = usage.get("promptTokenCount", 0)
            row.cached_tokens = usage.get("cachedContentTokenCount", 0)
            row.output_tokens = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        row.cost_microusd = cost
        balance = owner.model_credit_microusd + held.amount - cost
        if balance < 0:
            logger.warning("model usage %s cost more than its reservation", held.usage_id)
        owner.model_credit_microusd = max(balance, 0)
        await db.commit()
    logger.info(
        "llm proxy usage=%s status=%s upstream=%s cost_microusd=%s",
        held.usage_id, row.status, upstream_status, cost,
    )


async def _record_free(
    owner_id: uuid.UUID, agent_id: uuid.UUID, model: str, method: str, upstream_status: int
) -> None:
    async with session_factory() as db:
        db.add(ModelUsage(
            owner_id=owner_id,
            agent_id=agent_id,
            model=model,
            method=method,
            status="free",
            reserved_microusd=0,
            cost_microusd=0,
            upstream_status=upstream_status,
        ))
        await db.commit()


async def open_stream(path: str, params: dict, body: dict) -> UpstreamStream:
    client = upstream_client()
    request = client.build_request(
        "POST", path, params=params, content=encode(body), headers=_upstream_headers()
    )
    try:
        return UpstreamStream(client, await client.send(request, stream=True))
    except httpx.TransportError:
        await client.aclose()
        raise


async def relay_stream(stream: UpstreamStream, held: Held):
    """Pass Google's SSE through chunk by chunk and settle from the last usage
    figures it carried.

    If the client walks away mid-stream the generator is closed before the
    settle line, so the reservation stands.
    """
    usage = None
    pending = b""
    try:
        async for chunk in stream.response.aiter_bytes():
            yield chunk
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for line in lines:
                usage = _usage_from_sse_line(line) or usage
        usage = _usage_from_sse_line(pending) or usage
    finally:
        await stream.aclose()
    await settle(held, usage, stream.response.status_code)


def _usage_from_sse_line(line: bytes) -> dict | None:
    line = line.strip()
    if not line.startswith(b"data:"):
        return None
    return json.loads(line.removeprefix(b"data:")).get("usageMetadata")


def _passthrough(response: httpx.Response) -> Response:
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type"),
    )


@app.post("/llm/v1beta/models/{target}")
async def proxy(target: str, request: Request) -> Response:
    model, _, method = target.partition(":")
    try:
        if method not in BILLED_METHODS | FREE_METHODS:
            raise ProxyError(404, f"Method {method!r} is not available through Koala")
        agent_id, owner_id = await authenticate(_client_key(request))
        if not await anyio.to_thread.run_sync(rate_limiter.hit, RATE_LIMIT, "llm-proxy", str(agent_id)):
            raise ProxyError(429, "Rate limit: 60 model calls per minute per agent")
        if model not in MODELS:
            raise ProxyError(
                403,
                f"Model {model!r} is not available through Koala; available: {', '.join(MODELS)}",
            )
        try:
            body = await request.json()
        except ValueError:
            raise ProxyError(400, "Request body is not JSON")

        path = f"/v1beta/models/{model}:{method}"
        params = {k: v for k, v in request.query_params.items() if k != "key"}

        if method in FREE_METHODS:
            try:
                async with upstream_client() as client:
                    response = await client.post(
                        path, params=params, content=encode(body), headers=_upstream_headers()
                    )
            except httpx.TransportError:
                raise ProxyError(502, UNREACHABLE)
            await _record_free(owner_id, agent_id, model, method, response.status_code)
            return _passthrough(response)

        if method == "streamGenerateContent" and params.get("alt") != "sse":
            raise ProxyError(
                400, "streamGenerateContent needs alt=sse: other stream formats cannot be metered"
            )
        try:
            body = clamp(body)
        except RequestRejected as exc:
            raise ProxyError(400, str(exc))
        held = await reserve(owner_id, agent_id, model, method, body)

        if method == "generateContent":
            try:
                async with upstream_client() as client:
                    response = await client.post(
                        path, params=params, content=encode(body), headers=_upstream_headers()
                    )
                usage = response.json().get("usageMetadata") if response.is_success else None
            except (httpx.TransportError, ValueError):
                await settle(held, None, 502)
                raise ProxyError(502, UNREACHABLE)
            await settle(held, usage, response.status_code)
            return _passthrough(response)

        try:
            stream = await open_stream(path, params, body)
        except httpx.TransportError:
            await settle(held, None, 502)
            raise ProxyError(502, UNREACHABLE)
        if not stream.response.is_success:
            await stream.response.aread()
            await stream.aclose()
            await settle(held, None, stream.response.status_code)
            return _passthrough(stream.response)
        return StreamingResponse(
            relay_stream(stream, held),
            media_type=stream.response.headers.get("content-type"),
        )
    except ProxyError as exc:
        return _error(exc.code, exc.message)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def not_proxied(path: str) -> JSONResponse:
    return _error(404, "Only generateContent, streamGenerateContent and countTokens are available through Koala")
