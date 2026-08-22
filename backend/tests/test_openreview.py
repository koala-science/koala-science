"""The authenticated OpenReview profile client.

The bug this file exists to prevent: OpenReview answers anonymous requests with
`403 ChallengeRequiredError`, and the previous client treated any non-404, non-5xx
response as "no profiles in the payload" — so a challenge read as "this profile
does not exist" and every signup was rejected. A 403 must raise.
"""
import httpx
import pytest

from app.core import openreview as orv
from app.core.openreview import (
    OpenReviewUnavailableError,
    fetch_profile,
)

CHALLENGE_BODY = {
    "name": "ChallengeRequiredError",
    "message": "Challenge verification required",
    "status": 403,
}

PROFILE_BODY = {
    "profiles": [
        {
            "id": "~Alice_Chen1",
            "content": {
                "names": [{"preferred": True, "fullname": "Alice Chen"}],
                "emails": ["****@mila.quebec", "****@gmail.com"],
            },
        }
    ]
}


class _Recorder:
    """Stands in for httpx.AsyncClient, replaying queued responses."""

    def __init__(self, *responses):
        self.queued = list(responses)
        self.requests: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def _next(self, method, url):
        self.requests.append((method, url))
        item = self.queued.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url, **kw):
        return self._next("GET", url)

    async def post(self, url, **kw):
        return self._next("POST", url)


def _resp(status, body=None):
    return httpx.Response(status, json=body if body is not None else {})


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    monkeypatch.setattr(orv.settings, "OPENREVIEW_USERNAME", "bot@koala.science")
    monkeypatch.setattr(orv.settings, "OPENREVIEW_PASSWORD", "secret")
    monkeypatch.setattr(orv.settings, "OPENREVIEW_TOKEN", "")
    orv.reset_token_cache()
    yield
    orv.reset_token_cache()


def _install(monkeypatch, recorder):
    monkeypatch.setattr(orv.httpx, "AsyncClient", lambda **kw: recorder)


async def test_challenge_response_raises_rather_than_denying_the_profile(monkeypatch):
    """The regression. A 403 must never read as 'profile does not exist'."""
    recorder = _Recorder(_resp(200, {"token": "t"}), _resp(403, CHALLENGE_BODY))
    _install(monkeypatch, recorder)

    with pytest.raises(OpenReviewUnavailableError):
        await fetch_profile("~Alice_Chen1")


async def test_fetch_profile_returns_name_and_email_domains(monkeypatch):
    recorder = _Recorder(_resp(200, {"token": "t"}), _resp(200, PROFILE_BODY))
    _install(monkeypatch, recorder)

    profile = await fetch_profile("~Alice_Chen1")

    assert profile.id == "~Alice_Chen1"
    assert profile.name == "Alice Chen"
    assert profile.email_domains == ("mila.quebec", "gmail.com")


async def test_missing_profile_is_none_not_an_error(monkeypatch):
    recorder = _Recorder(_resp(200, {"token": "t"}), _resp(200, {"profiles": []}))
    _install(monkeypatch, recorder)

    assert await fetch_profile("~Ghost_User1") is None


async def test_404_is_none(monkeypatch):
    recorder = _Recorder(_resp(200, {"token": "t"}), _resp(404, {}))
    _install(monkeypatch, recorder)

    assert await fetch_profile("~Ghost_User1") is None


async def test_5xx_raises(monkeypatch):
    recorder = _Recorder(_resp(200, {"token": "t"}), _resp(503, {}))
    _install(monkeypatch, recorder)

    with pytest.raises(OpenReviewUnavailableError):
        await fetch_profile("~Alice_Chen1")


async def test_network_error_raises(monkeypatch):
    recorder = _Recorder(_resp(200, {"token": "t"}), httpx.ConnectError("boom"))
    _install(monkeypatch, recorder)

    with pytest.raises(OpenReviewUnavailableError):
        await fetch_profile("~Alice_Chen1")


async def test_token_is_reused_across_calls(monkeypatch):
    recorder = _Recorder(
        _resp(200, {"token": "t"}),
        _resp(200, PROFILE_BODY),
        _resp(200, PROFILE_BODY),
    )
    _install(monkeypatch, recorder)

    await fetch_profile("~Alice_Chen1")
    await fetch_profile("~Alice_Chen1")

    logins = [r for r in recorder.requests if r[0] == "POST"]
    assert len(logins) == 1, "should log in once and reuse the token"


async def test_expired_token_triggers_one_relogin(monkeypatch):
    """A 401 means the cached token died early; log in again and retry once."""
    recorder = _Recorder(
        _resp(200, {"token": "old"}),
        _resp(401, {}),
        _resp(200, {"token": "new"}),
        _resp(200, PROFILE_BODY),
    )
    _install(monkeypatch, recorder)

    profile = await fetch_profile("~Alice_Chen1")

    assert profile.name == "Alice Chen"
    assert len([r for r in recorder.requests if r[0] == "POST"]) == 2


async def test_missing_credentials_is_unavailable_not_missing(monkeypatch):
    monkeypatch.setattr(orv.settings, "OPENREVIEW_USERNAME", "")
    monkeypatch.setattr(orv.settings, "OPENREVIEW_PASSWORD", "")

    with pytest.raises(OpenReviewUnavailableError):
        await fetch_profile("~Alice_Chen1")


async def test_failed_login_is_unavailable(monkeypatch):
    recorder = _Recorder(_resp(400, {"message": "bad password"}))
    _install(monkeypatch, recorder)

    with pytest.raises(OpenReviewUnavailableError):
        await fetch_profile("~Alice_Chen1")


async def test_a_configured_token_is_used_without_logging_in(monkeypatch):
    """An operator may supply a bearer token instead of credentials."""
    monkeypatch.setattr(orv.settings, "OPENREVIEW_TOKEN", "preissued")
    recorder = _Recorder(_resp(200, PROFILE_BODY))
    _install(monkeypatch, recorder)

    profile = await fetch_profile("~Alice_Chen1")

    assert profile.name == "Alice Chen"
    assert [r for r in recorder.requests if r[0] == "POST"] == [], "must not log in"


async def test_a_profile_without_an_id_is_unavailable_not_a_profile(monkeypatch):
    """`pending_openreview_id` is NOT NULL, so an id-less profile would 500."""
    recorder = _Recorder(
        _resp(200, {"token": "t"}),
        _resp(200, {"profiles": [{"content": {"emails": ["****@mila.quebec"]}}]}),
    )
    _install(monkeypatch, recorder)

    with pytest.raises(OpenReviewUnavailableError):
        await fetch_profile("~Alice_Chen1")
