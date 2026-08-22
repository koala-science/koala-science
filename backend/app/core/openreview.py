"""Authenticated client for OpenReview's profile API.

OpenReview no longer serves this API anonymously: unauthenticated requests come
back as ``403 ChallengeRequiredError``. Everything here therefore runs behind a
bearer token obtained from ``POST /login`` and cached until it expires.

What the API will and will not tell us, established by probing it:

* A third party's ``content.emails`` are masked to ``****@domain``. The local
  part is gone entirely, so we can compare **domains** and nothing finer.
* There is no lookup in the other direction — no endpoint answers "which profile
  owns this address". ``?email=``, ``?confirmedEmail=`` and ``?emails=`` are all
  rejected by the request schema, and ``/profiles/search`` insists on ``ids``.

That shape is what forces the signup check to be "the address is at a domain this
profile lists, and the address is proven by a link" rather than an exact match.
"""
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

OPENREVIEW_BASE_URL = "https://api2.openreview.net"
REQUEST_TIMEOUT_SECONDS = 10.0

# Tokens last a few hours; re-login well inside that. A 401 forces one anyway.
TOKEN_TTL_SECONDS = 60 * 60


class OpenReviewUnavailableError(Exception):
    """OpenReview could not answer. Never means "this profile does not exist"."""


@dataclass(frozen=True)
class OpenReviewProfile:
    id: str
    name: str | None
    email_domains: tuple[str, ...]


_token: str | None = None
_token_expires_at: float = 0.0


def reset_token_cache() -> None:
    """Drop the cached token. For tests, and after a 401."""
    global _token, _token_expires_at
    _token, _token_expires_at = None, 0.0


async def _login(client: httpx.AsyncClient) -> str:
    if not settings.OPENREVIEW_USERNAME or not settings.OPENREVIEW_PASSWORD:
        raise OpenReviewUnavailableError("OpenReview credentials are not configured")

    try:
        response = await client.post(
            f"{OPENREVIEW_BASE_URL}/login",
            json={
                "id": settings.OPENREVIEW_USERNAME,
                "password": settings.OPENREVIEW_PASSWORD,
            },
        )
    except httpx.HTTPError as exc:
        raise OpenReviewUnavailableError(f"OpenReview login failed: {exc}") from exc

    if response.status_code != 200:
        raise OpenReviewUnavailableError(
            f"OpenReview login returned {response.status_code}"
        )

    token = response.json().get("token")
    if not token:
        raise OpenReviewUnavailableError("OpenReview login returned no token")

    global _token, _token_expires_at
    _token = token
    _token_expires_at = time.monotonic() + TOKEN_TTL_SECONDS
    return token


async def _token_for(client: httpx.AsyncClient) -> str:
    if settings.OPENREVIEW_TOKEN:
        return settings.OPENREVIEW_TOKEN

    if _token and time.monotonic() < _token_expires_at:
        return _token
    return await _login(client)


def _parse_profile(payload: dict) -> OpenReviewProfile | None:
    profiles = payload.get("profiles", [])
    if not profiles:
        return None

    profile = profiles[0]
    content = profile.get("content", {})

    names = content.get("names") or []
    preferred = next((n for n in names if n.get("preferred")), names[0] if names else {})
    name = preferred.get("fullname")

    domains = []
    for masked in content.get("emails") or []:
        _, _, domain = str(masked).rpartition("@")
        if domain:
            domains.append(domain.lower())

    profile_id = profile.get("id")
    if not profile_id:
        raise OpenReviewUnavailableError("OpenReview returned a profile with no id")

    return OpenReviewProfile(
        id=profile_id,
        name=name,
        email_domains=tuple(domains),
    )


async def fetch_profile(openreview_id: str) -> OpenReviewProfile | None:
    """The profile, or None if OpenReview has no such ID.

    Raises ``OpenReviewUnavailableError`` for every other failure — including a
    403 challenge, which is the whole point of this module: an unanswerable
    request must not be reported to the user as a profile that does not exist.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        token = await _token_for(client)

        try:
            response = await client.get(
                f"{OPENREVIEW_BASE_URL}/profiles",
                params={"id": openreview_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 401:
                reset_token_cache()
                token = await _login(client)
                response = await client.get(
                    f"{OPENREVIEW_BASE_URL}/profiles",
                    params={"id": openreview_id},
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise OpenReviewUnavailableError(
                f"OpenReview request failed: {exc}"
            ) from exc

        if response.status_code == 404:
            return None

        if response.status_code != 200:
            logger.warning(
                "OpenReview profile lookup returned %s for %s",
                response.status_code, openreview_id,
            )
            raise OpenReviewUnavailableError(
                f"OpenReview returned {response.status_code}"
            )

        return _parse_profile(response.json())
