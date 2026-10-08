"""The Gemini proxy: agents call Gemini with their Koala key, against their
owner's one-off model credit, and never see the server's key.

Google is stubbed at the httpx transport; nothing here leaves the machine.
"""
import asyncio
import json
import uuid

import anyio
import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.llm_proxy import main as proxy
from app.llm_proxy.registry import (
    MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    MAX_THINKING_TOKENS,
    MODELS,
    clamp,
    reservation,
    usage_cost,
)
from app.models.identity import HumanAccount
from app.models.platform import ModelUsage
from tests.conftest import complete_signup

FLASH = "gemini-3.5-flash"
SERVER_KEY = "server-secret-key-do-not-leak"
USAGE = {
    "promptTokenCount": 1200,
    "cachedContentTokenCount": 200,
    "candidatesTokenCount": 300,
    "thoughtsTokenCount": 100,
}
PROMPT = "Please review the secret manuscript about kangaroos."
BODY = {"contents": [{"role": "user", "parts": [{"text": PROMPT}]}]}


class Upstream:
    """A fake Google: records what it was sent and answers as configured."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.usage = USAGE

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": self.status, "message": "boom"}})
        if ":countTokens" in request.url.path:
            return httpx.Response(200, json={"totalTokens": 42})
        if ":streamGenerateContent" in request.url.path:
            chunks = [
                {"candidates": [{"content": {"parts": [{"text": "Hel"}]}}]},
                {"candidates": [{"content": {"parts": [{"text": "lo"}]}}], "usageMetadata": self.usage},
            ]
            sse = "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks)
            return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "Hello"}]}}],
            "usageMetadata": self.usage,
        })


@pytest.fixture
async def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(settings, "GEMINI_API_KEY", SERVER_KEY)
    monkeypatch.setattr(
        proxy,
        "upstream_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(fake.handler), base_url=settings.GEMINI_UPSTREAM_URL
        ),
    )
    return fake


@pytest.fixture
async def llm(monkeypatch) -> AsyncClient:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    monkeypatch.setattr(
        proxy, "session_factory", async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    )
    monkeypatch.setattr(proxy, "rate_limiter", MovingWindowRateLimiter(storage_from_string("memory://")))
    async with AsyncClient(transport=ASGITransport(app=proxy.app), base_url="http://llm") as c:
        yield c
    await engine.dispose()


async def _owner(client: AsyncClient) -> tuple[str, str]:
    prefix = uuid.uuid4().hex[:8]
    return await complete_signup(client, {
        "name": "Owner",
        "email": f"llm_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Llm_Owner_{prefix}1",
    })


async def _agent(client: AsyncClient, token: str) -> str:
    name = f"llm_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


async def _exec(sql: str, params: dict) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL))
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)
    await engine.dispose()


async def _set_credit(owner_id: str, microusd: int) -> None:
    await _exec("UPDATE human_account SET model_credit_microusd = :c WHERE id = :id",
                {"c": microusd, "id": owner_id})


async def _credit(db_session, owner_id: str) -> int:
    return (
        await db_session.execute(
            select(HumanAccount.model_credit_microusd).where(HumanAccount.id == uuid.UUID(owner_id))
        )
    ).scalar_one()


async def _ledger(db_session, owner_id: str) -> list[ModelUsage]:
    return list((
        await db_session.execute(
            select(ModelUsage).where(ModelUsage.owner_id == uuid.UUID(owner_id)).order_by(ModelUsage.created_at)
        )
    ).scalars())


def _generate(llm: AsyncClient, key: str, model: str = FLASH, body: dict = BODY, **kw):
    return llm.post(
        f"/llm/v1beta/models/{model}:generateContent",
        json=body,
        headers={"x-goog-api-key": key},
        **kw,
    )


@pytest.fixture
async def setup(client: AsyncClient, upstream, llm):
    token, owner_id = await _owner(client)
    key = await _agent(client, token)
    return {"token": token, "owner": owner_id, "key": key}


# --- the arithmetic ---------------------------------------------------------

PRICE = MODELS[FLASH]


@pytest.mark.parametrize("usage,expected", [
    ({}, 0),
    ({"promptTokenCount": 1_000_000}, PRICE.input),
    ({"promptTokenCount": 1_000_000, "cachedContentTokenCount": 1_000_000}, PRICE.cached_input),
    ({"candidatesTokenCount": 1_000_000}, PRICE.output),
    ({"thoughtsTokenCount": 1_000_000}, PRICE.output),
    ({"toolUsePromptTokenCount": 1_000_000}, PRICE.input),
    ({"promptTokenCount": 1}, 2),
    (USAGE, 1000 * PRICE.input // 1_000_000 + 200 * PRICE.cached_input // 1_000_000
     + 400 * PRICE.output // 1_000_000),
])
def test_usage_is_priced_from_the_registry_and_rounded_up(usage, expected):
    """Cached tokens are part of the prompt count but priced lower, thinking is
    output, and a fraction of a micro-dollar is charged as a whole one."""
    assert usage_cost(PRICE, usage) == expected


def test_the_one_model_is_the_one_gemini_cli_asks_for():
    """Gemini CLI 0.60 sends its default flash requests as gemini-3.5-flash;
    pricing any other single model would turn every CLI agent away."""
    assert list(MODELS) == ["gemini-3.5-flash"]


# --- auth -----------------------------------------------------------------

@pytest.mark.parametrize("how", ["x-goog-api-key", "query", "bearer"])
async def test_every_way_a_gemini_client_sends_its_key_works(setup, llm, upstream, how):
    key = setup["key"]
    headers, params = {}, {}
    if how == "x-goog-api-key":
        headers["x-goog-api-key"] = key
    elif how == "query":
        params["key"] = key
    else:
        headers["Authorization"] = f"Bearer {key}"

    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:generateContent", json=BODY, headers=headers, params=params
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"][0]["content"]["parts"][0]["text"] == "Hello"


@pytest.mark.parametrize("how", ["x-goog-api-key", "query", "bearer"])
async def test_upstream_sees_only_the_server_key(setup, llm, upstream, how):
    key = setup["key"]
    headers = {"x-goog-api-key": key} if how == "x-goog-api-key" else (
        {"Authorization": f"Bearer {key}"} if how == "bearer" else {}
    )
    params = {"key": key} if how == "query" else {}
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:generateContent", json=BODY, headers=headers, params=params
    )
    assert resp.status_code == 200, resp.text

    sent = upstream.requests[-1]
    assert sent.headers["x-goog-api-key"] == SERVER_KEY
    assert setup["key"] not in str(sent.url)
    assert setup["key"] not in "".join(f"{k}:{v}" for k, v in sent.headers.items())
    assert SERVER_KEY not in resp.text


async def test_a_bad_key_is_refused(setup, llm, upstream):
    resp = await _generate(llm, "cs_not_a_real_key")
    assert resp.status_code == 401
    assert upstream.requests == []


async def test_no_key_is_refused(setup, llm, upstream):
    resp = await llm.post(f"/llm/v1beta/models/{FLASH}:generateContent", json=BODY)
    assert resp.status_code == 401
    assert upstream.requests == []


async def test_a_human_token_is_refused(setup, llm, upstream):
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:generateContent",
        json=BODY,
        headers={"Authorization": f"Bearer {setup['token']}"},
    )
    assert resp.status_code == 403
    assert upstream.requests == []


async def test_a_deactivated_agent_is_refused(setup, llm, upstream):
    await _exec(
        "UPDATE actor SET is_active = false WHERE id IN (SELECT id FROM agent WHERE owner_id = :o)",
        {"o": setup["owner"]},
    )
    resp = await _generate(llm, setup["key"])
    assert resp.status_code == 403
    assert upstream.requests == []


# --- what is proxied ------------------------------------------------------

async def test_a_model_outside_the_registry_is_refused(setup, llm, upstream):
    resp = await _generate(llm, setup["key"], model="gemini-2.5-flash")
    assert resp.status_code == 403
    assert "not available through Koala" in resp.json()["error"]["message"]
    assert upstream.requests == []


@pytest.mark.parametrize("path", [
    f"/llm/v1beta/models/{FLASH}:batchEmbedContents",
    f"/llm/v1beta/models/{FLASH}:somethingElse",
    "/llm/v1beta/files",
])
async def test_anything_else_is_not_found(setup, llm, upstream, path):
    resp = await llm.post(path, json=BODY, headers={"x-goog-api-key": setup["key"]})
    assert resp.status_code == 404
    assert "error" in resp.json()
    assert upstream.requests == []


async def test_output_and_thinking_are_clamped(setup, llm, upstream):
    body = {**BODY, "generationConfig": {
        "maxOutputTokens": 10 * MAX_OUTPUT_TOKENS,
        "temperature": 0.3,
        "thinkingConfig": {"thinkingBudget": -1, "includeThoughts": True},
    }}
    assert (await _generate(llm, setup["key"], body=body)).status_code == 200

    sent = json.loads(upstream.requests[-1].content)
    config = sent["generationConfig"]
    assert config["maxOutputTokens"] == MAX_OUTPUT_TOKENS
    assert config["thinkingConfig"]["thinkingBudget"] == MAX_THINKING_TOKENS
    assert config["thinkingConfig"]["includeThoughts"] is True
    assert config["temperature"] == 0.3
    assert sent["contents"] == BODY["contents"]


async def test_requests_within_the_clamps_pass_unchanged(setup, llm, upstream):
    body = {**BODY, "generationConfig": {"maxOutputTokens": 100, "thinkingConfig": {"thinkingBudget": 0}}}
    assert (await _generate(llm, setup["key"], body=body)).status_code == 200

    config = json.loads(upstream.requests[-1].content)["generationConfig"]
    assert config["maxOutputTokens"] == 100
    assert config["thinkingConfig"]["thinkingBudget"] == 0


async def test_a_body_without_config_gets_the_clamps(setup, llm, upstream):
    assert (await _generate(llm, setup["key"])).status_code == 200

    config = json.loads(upstream.requests[-1].content)["generationConfig"]
    assert config["maxOutputTokens"] == MAX_OUTPUT_TOKENS
    assert config["thinkingConfig"]["thinkingBudget"] == MAX_THINKING_TOKENS


# --- credit ----------------------------------------------------------------

async def test_a_new_account_starts_with_ten_dollars(setup, db_session):
    assert await _credit(db_session, setup["owner"]) == 10_000_000


async def test_a_call_costs_exactly_what_google_reports(setup, llm, db_session):
    for _ in range(3):
        assert (await _generate(llm, setup["key"])).status_code == 200

    expected = usage_cost(MODELS[FLASH], USAGE)
    assert await _credit(db_session, setup["owner"]) == 10_000_000 - 3 * expected

    rows = await _ledger(db_session, setup["owner"])
    assert [r.status for r in rows] == ["settled"] * 3
    assert [r.cost_microusd for r in rows] == [expected] * 3
    assert rows[0].prompt_tokens == 1200
    assert rows[0].cached_tokens == 200
    assert rows[0].output_tokens == 400
    assert rows[0].model == FLASH
    assert rows[0].upstream_status == 200


async def test_too_little_credit_is_refused_before_google_is_called(setup, llm, upstream, db_session):
    await _set_credit(setup["owner"], 10)
    resp = await _generate(llm, setup["key"])

    assert resp.status_code == 402
    assert "credit" in resp.json()["error"]["message"].lower()
    assert upstream.requests == []
    assert await _credit(db_session, setup["owner"]) == 10
    assert await _ledger(db_session, setup["owner"]) == []


async def test_an_upstream_error_refunds_everything(setup, llm, upstream, db_session):
    upstream.status = 500
    resp = await _generate(llm, setup["key"])

    assert resp.status_code == 500
    assert await _credit(db_session, setup["owner"]) == 10_000_000
    [row] = await _ledger(db_session, setup["owner"])
    assert row.status == "upstream_error"
    assert row.cost_microusd == 0
    assert row.upstream_status == 500


async def test_a_response_without_usage_keeps_the_reservation(setup, llm, upstream, db_session):
    upstream.usage = None
    assert (await _generate(llm, setup["key"])).status_code == 200

    [row] = await _ledger(db_session, setup["owner"])
    assert row.reserved_microusd > 0
    assert row.cost_microusd == row.reserved_microusd
    assert await _credit(db_session, setup["owner"]) == 10_000_000 - row.reserved_microusd


async def test_count_tokens_is_free(setup, llm, upstream, db_session):
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:countTokens", json=BODY, headers={"x-goog-api-key": setup["key"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"totalTokens": 42}
    assert await _credit(db_session, setup["owner"]) == 10_000_000
    [row] = await _ledger(db_session, setup["owner"])
    assert row.method == "countTokens"
    assert row.cost_microusd == 0


async def test_count_tokens_works_with_no_credit_left(setup, llm, upstream):
    await _set_credit(setup["owner"], 0)
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:countTokens", json=BODY, headers={"x-goog-api-key": setup["key"]}
    )
    assert resp.status_code == 200, resp.text


async def test_sibling_agents_cannot_overspend_in_parallel(
    client, setup, llm, upstream, db_session, monkeypatch
):
    """Credit for one call's reservation, two agents racing: the lock decides.

    The pause after reading the balance makes the race certain: without the
    lock, both requests read the same balance before either writes."""
    original = proxy._lock_owner

    async def _slow_lock(db, owner_id):
        owner = await original(db, owner_id)
        await asyncio.sleep(0.1)
        return owner

    monkeypatch.setattr(proxy, "_lock_owner", _slow_lock)
    second_key = await _agent(client, setup["token"])
    one_call = reservation(MODELS[FLASH], clamp(BODY))
    await _set_credit(setup["owner"], one_call)

    first, second = await asyncio.gather(_generate(llm, setup["key"]), _generate(llm, second_key))

    assert sorted([first.status_code, second.status_code]) == [200, 402]
    assert len(upstream.requests) == 1
    assert await _credit(db_session, setup["owner"]) == one_call - usage_cost(MODELS[FLASH], USAGE)


async def test_the_credit_is_pooled_across_an_owners_agents(client, setup, llm, db_session):
    second_key = await _agent(client, setup["token"])
    assert (await _generate(llm, setup["key"])).status_code == 200
    assert (await _generate(llm, second_key)).status_code == 200

    assert await _credit(db_session, setup["owner"]) == 10_000_000 - 2 * usage_cost(MODELS[FLASH], USAGE)


async def test_the_ledger_holds_no_prompt_or_response_text(setup, llm, db_session):
    assert (await _generate(llm, setup["key"])).status_code == 200

    [row] = await _ledger(db_session, setup["owner"])
    stored = " ".join(str(getattr(row, c.key)) for c in ModelUsage.__table__.columns)
    assert "kangaroos" not in stored
    assert "Hello" not in stored


async def test_nothing_secret_is_logged(setup, llm, upstream, caplog):
    caplog.set_level("DEBUG")
    assert (await _generate(llm, setup["key"])).status_code == 200
    upstream.status = 500
    await _generate(llm, setup["key"])

    logged = caplog.text
    assert SERVER_KEY not in logged
    assert setup["key"] not in logged
    assert "kangaroos" not in logged


# --- streaming -------------------------------------------------------------

def _stream(llm: AsyncClient, key: str):
    return llm.post(
        f"/llm/v1beta/models/{FLASH}:streamGenerateContent",
        params={"alt": "sse"},
        json=BODY,
        headers={"x-goog-api-key": key},
    )


async def test_a_stream_is_relayed_and_settled_from_its_last_chunk(setup, llm, upstream, db_session):
    resp = await _stream(llm, setup["key"])

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    texts = [
        json.loads(line.removeprefix("data: "))["candidates"][0]["content"]["parts"][0]["text"]
        for line in resp.text.splitlines() if line.startswith("data: ")
    ]
    assert texts == ["Hel", "lo"]
    assert upstream.requests[-1].url.params["alt"] == "sse"

    [row] = await _ledger(db_session, setup["owner"])
    assert row.status == "settled"
    assert row.cost_microusd == usage_cost(MODELS[FLASH], USAGE)
    assert await _credit(db_session, setup["owner"]) == 10_000_000 - row.cost_microusd


async def test_a_stream_error_refunds_everything(setup, llm, upstream, db_session):
    upstream.status = 429
    resp = await _stream(llm, setup["key"])

    assert resp.status_code == 429
    assert await _credit(db_session, setup["owner"]) == 10_000_000


async def test_an_abandoned_stream_keeps_the_reservation(setup, upstream, db_session):
    """Google may bill a stream the client walked away from, and nothing says
    how much — so the worst case stands."""
    agent_id, owner_id = await proxy.authenticate(setup["key"])
    held = await proxy.reserve(owner_id, agent_id, FLASH, "streamGenerateContent", clamp(BODY))
    relay = proxy.relay_stream(
        await proxy.open_stream(f"/v1beta/models/{FLASH}:streamGenerateContent", {"alt": "sse"}, BODY),
        held,
    )

    first = await relay.__anext__()
    assert b"Hel" in first
    await relay.aclose()

    [row] = await _ledger(db_session, setup["owner"])
    assert row.status == "reserved"
    assert row.cost_microusd == row.reserved_microusd
    assert await _credit(db_session, setup["owner"]) == 10_000_000 - row.reserved_microusd


# --- rate limit ------------------------------------------------------------

async def test_the_sixty_first_call_in_a_minute_is_refused(setup, llm, upstream):
    for _ in range(60):
        resp = await llm.post(
            f"/llm/v1beta/models/{FLASH}:countTokens", json=BODY, headers={"x-goog-api-key": setup["key"]}
        )
        assert resp.status_code == 200, resp.text

    resp = await _generate(llm, setup["key"])
    assert resp.status_code == 429
    assert len(upstream.requests) == 60


# --- visibility -----------------------------------------------------------

async def test_the_profile_reports_the_model_credit(client, setup, llm):
    assert (await _generate(llm, setup["key"])).status_code == 200
    spent = usage_cost(MODELS[FLASH], USAGE)

    for who in (setup["token"], setup["key"]):
        profile = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {who}"})
        assert profile.status_code == 200, profile.text
        assert profile.json()["model_credit_usd"] == pytest.approx((10_000_000 - spent) / 1_000_000)


# --- review fixes: logs, cost bounds, malformed input, transport failures ---

@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.staging.yml", "docker-compose.prod.yml"])
def test_the_proxy_never_writes_an_access_log(compose):
    """An access log records the query string, and ``?key=`` is a way agents
    send their key."""
    import pathlib

    import yaml

    path = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "docker" / compose
    command = yaml.safe_load(path.read_text())["services"]["llm-proxy"]["command"]
    assert command[:2] == ["uvicorn", "app.llm_proxy.main:app"], f"llm-proxy command reshaped: {command}"
    assert "--no-access-log" in command


async def test_only_one_candidate_is_ever_requested(setup, llm, upstream):
    """The output cap applies per candidate, so eight candidates would cost
    eight times what was reserved."""
    body = {**BODY, "generationConfig": {"candidateCount": 8}}
    assert (await _generate(llm, setup["key"], body=body)).status_code == 200
    assert json.loads(upstream.requests[-1].content)["generationConfig"]["candidateCount"] == 1


async def test_function_declarations_are_allowed(setup, llm, upstream):
    body = {**BODY, "tools": [{"functionDeclarations": [{"name": "read_file", "description": "d"}]}]}
    assert (await _generate(llm, setup["key"], body=body)).status_code == 200
    assert json.loads(upstream.requests[-1].content)["tools"] == body["tools"]


@pytest.mark.parametrize("tool", [{"googleSearch": {}}, {"urlContext": {}}, {"codeExecution": {}}])
async def test_tools_billed_outside_the_reservation_are_refused(setup, llm, upstream, db_session, tool):
    """Search is billed per request and URL context pulls in pages the body
    does not contain, so neither is bounded by what was reserved."""
    resp = await _generate(llm, setup["key"], body={**BODY, "tools": [tool]})
    assert resp.status_code == 400
    assert upstream.requests == []
    assert await _credit(db_session, setup["owner"]) == 10_000_000


async def test_file_references_are_refused(setup, llm, upstream):
    """A short URI can stand for hours of video, unbounded by the body's size."""
    body = {"contents": [{"role": "user", "parts": [
        {"fileData": {"fileUri": "https://www.youtube.com/watch?v=x", "mimeType": "video/mp4"}}
    ]}]}
    resp = await _generate(llm, setup["key"], body=body)
    assert resp.status_code == 400
    assert upstream.requests == []


def test_the_reservation_covers_a_token_per_byte():
    """Digits tokenise one per byte, so nothing denser than that is assumed."""
    body = clamp({"contents": [{"role": "user", "parts": [{"text": "7" * 40_000}]}]})
    worst = usage_cost(PRICE, {
        "promptTokenCount": 40_000,
        "candidatesTokenCount": MAX_OUTPUT_TOKENS,
        "thoughtsTokenCount": MAX_THINKING_TOKENS,
    })
    assert reservation(PRICE, body) >= worst


async def test_a_stream_must_ask_for_server_sent_events(setup, llm, upstream, db_session):
    """Without ``alt=sse`` Google streams a JSON array the proxy cannot meter,
    which would charge the worst case every time."""
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:streamGenerateContent", json=BODY, headers={"x-goog-api-key": setup["key"]}
    )
    assert resp.status_code == 400
    assert "alt=sse" in resp.json()["error"]["message"]
    assert upstream.requests == []
    assert await _credit(db_session, setup["owner"]) == 10_000_000


@pytest.mark.parametrize("body", [
    b"[1, 2]",
    b'{"contents": [], "generationConfig": null}',
    b'{"contents": [], "generationConfig": {"maxOutputTokens": null}}',
    b'{"contents": [], "generationConfig": {"thinkingConfig": {"thinkingBudget": "lots"}}}',
    b"\xff\xfe not utf-8",
    b"not json",
])
async def test_a_malformed_body_is_a_400(setup, llm, upstream, db_session, body):
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:generateContent",
        content=body,
        headers={"x-goog-api-key": setup["key"], "content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert upstream.requests == []
    assert await _credit(db_session, setup["owner"]) == 10_000_000


async def test_a_non_bearer_authorization_header_is_no_key(setup, llm, upstream):
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:generateContent",
        json=BODY,
        headers={"Authorization": f"Basic {setup['key']}"},
    )
    assert resp.status_code == 401


@pytest.fixture
def unreachable(monkeypatch):
    """Google cannot be reached at all."""
    def _refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SERVER_KEY)
    monkeypatch.setattr(
        proxy, "upstream_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_refuse), base_url=settings.GEMINI_UPSTREAM_URL),
    )


@pytest.mark.parametrize("method,params", [
    ("generateContent", {}),
    ("streamGenerateContent", {"alt": "sse"}),
])
async def test_unreachable_google_is_a_502_and_costs_nothing(
    client, llm, db_session, unreachable, method, params
):
    token, owner_id = await _owner(client)
    key = await _agent(client, token)

    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:{method}", params=params, json=BODY, headers={"x-goog-api-key": key}
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["status"] == "UNAVAILABLE"
    assert await _credit(db_session, owner_id) == 10_000_000
    [row] = await _ledger(db_session, owner_id)
    assert row.status == "upstream_error"


async def test_a_success_that_is_not_json_is_a_502_and_costs_nothing(setup, llm, upstream, db_session, monkeypatch):
    monkeypatch.setattr(
        proxy, "upstream_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>oops</html>")),
            base_url=settings.GEMINI_UPSTREAM_URL,
        ),
    )
    resp = await _generate(llm, setup["key"])
    assert resp.status_code == 502
    assert await _credit(db_session, setup["owner"]) == 10_000_000


class _PooledTransport(httpx.AsyncBaseTransport):
    """Closes the way a real connection pool does: with an await, which is
    exactly where an unshielded close gets cancelled."""

    def __init__(self, handler):
        self._mock = httpx.MockTransport(handler)
        self.closed = False

    async def handle_async_request(self, request):
        return await self._mock.handle_async_request(request)

    async def aclose(self):
        await anyio.sleep(0)
        self.closed = True


async def test_a_cancelled_stream_still_closes_its_upstream_connection(setup, db_session, monkeypatch):
    """A client disconnect cancels the task relaying the stream. Closing the
    upstream connection must survive that cancellation, and the reservation
    stands."""
    release = asyncio.Event()

    async def _endless():
        yield b'data: {"candidates": []}\r\n\r\n'
        await release.wait()

    transport = _PooledTransport(
        lambda r: httpx.Response(200, content=_endless(), headers={"content-type": "text/event-stream"})
    )
    monkeypatch.setattr(
        proxy, "upstream_client",
        lambda: httpx.AsyncClient(transport=transport, base_url=settings.GEMINI_UPSTREAM_URL),
    )
    agent_id, owner_id = await proxy.authenticate(setup["key"])
    held = await proxy.reserve(owner_id, agent_id, FLASH, "streamGenerateContent", clamp(BODY))
    stream = await proxy.open_stream(f"/v1beta/models/{FLASH}:streamGenerateContent", {"alt": "sse"}, BODY)

    async def _consume():
        async for _ in proxy.relay_stream(stream, held):
            pass

    # Cancelled the way Starlette cancels on disconnect: through an anyio
    # cancel scope, which keeps cancelling every await until the scope exits —
    # including the ones in a ``finally``.
    async with anyio.create_task_group() as tg:
        tg.start_soon(_consume)
        await asyncio.sleep(0.05)
        tg.cancel_scope.cancel()

    assert transport.closed
    [row] = await _ledger(db_session, setup["owner"])
    assert row.status == "reserved"


async def test_a_thinking_level_gives_way_to_the_budget_cap(setup, llm, upstream):
    """Gemini CLI asks Gemini 3 models for ``thinkingLevel: HIGH``; Google
    refuses a level and a budget together, and only the budget is a bound."""
    body = {**BODY, "generationConfig": {"thinkingConfig": {"thinkingLevel": "HIGH", "includeThoughts": True}}}
    assert (await _generate(llm, setup["key"], body=body)).status_code == 200

    thinking = json.loads(upstream.requests[-1].content)["generationConfig"]["thinkingConfig"]
    assert thinking == {"includeThoughts": True, "thinkingBudget": MAX_THINKING_TOKENS}


@pytest.mark.parametrize("where", ["contents", "systemInstruction"])
def test_inline_media_reserves_the_whole_context(where):
    """Media tokens do not follow bytes: a 100-byte image is hundreds of tokens,
    a small compressed video can be a million."""
    part = {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}}
    body = (
        {"contents": [{"role": "user", "parts": [part]}]}
        if where == "contents"
        else {"contents": [], "systemInstruction": {"parts": [part]}}
    )
    full_context = usage_cost(PRICE, {
        "promptTokenCount": MAX_INPUT_TOKENS,
        "candidatesTokenCount": MAX_OUTPUT_TOKENS,
        "thoughtsTokenCount": MAX_THINKING_TOKENS,
    })
    assert reservation(PRICE, clamp(body)) == full_context


def test_text_reserves_a_token_per_byte():
    body = clamp(BODY)
    assert reservation(PRICE, body) == usage_cost(PRICE, {
        "promptTokenCount": len(proxy.encode(body)),
        "candidatesTokenCount": MAX_OUTPUT_TOKENS,
        "thoughtsTokenCount": MAX_THINKING_TOKENS,
    })


@pytest.mark.parametrize("body", [
    b'{"contents": null}',
    b'{"contents": [], "tools": null}',
    b'{"contents": [{"role": "user", "parts": null}]}',
    b'{"contents": [], "systemInstruction": {"parts": [{"fileData": {"fileUri": "gs://x/y.mp4"}}]}}',
])
async def test_more_malformed_or_unbounded_bodies_are_a_400(setup, llm, upstream, body):
    resp = await llm.post(
        f"/llm/v1beta/models/{FLASH}:generateContent",
        content=body,
        headers={"x-goog-api-key": setup["key"], "content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert upstream.requests == []
