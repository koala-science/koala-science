"""Thin async client for OpenReview's public profile API.

Used at signup time to confirm the user-supplied OpenReview ID corresponds
to a real profile. Format validation lives in the Pydantic schema; this
module only cares about existence.
"""
import httpx


OPENREVIEW_API_URL = "https://api2.openreview.net/profiles"
REQUEST_TIMEOUT_SECONDS = 5.0


class OpenReviewUnavailableError(Exception):
    """Raised when OpenReview is unreachable or returns a 5xx response."""


async def profile_exists(openreview_id: str) -> bool:
    """Return True iff OpenReview has a profile with this exact ID.

    Raises OpenReviewUnavailableError on network errors or 5xx responses.
    A 404 or an empty ``profiles`` array both count as "does not exist".
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                OPENREVIEW_API_URL, params={"id": openreview_id}
            )
    except httpx.HTTPError as exc:
        raise OpenReviewUnavailableError(
            f"OpenReview request failed: {exc}"
        ) from exc

    if 500 <= response.status_code < 600:
        raise OpenReviewUnavailableError(
            f"OpenReview returned {response.status_code}"
        )

    if response.status_code == 404:
        return False

    payload = response.json()
    profiles = payload.get("profiles", [])
    return len(profiles) > 0
