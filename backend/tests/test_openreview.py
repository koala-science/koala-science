"""Unit tests for the OpenReview profile-existence client."""
import httpx
import pytest

from app.core.openreview import (
    OpenReviewUnavailableError,
    profile_exists,
)


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if 500 <= self.status_code < 600:
            raise httpx.HTTPStatusError(
                "server error", request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )


class _FakeAsyncClient:
    def __init__(self, response=None, raise_exc: Exception | None = None, **_):
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url: str, params: dict | None = None):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


async def test_profile_exists_returns_true_for_populated_response(monkeypatch):
    response = _FakeResponse(200, {"profiles": [{"id": "~Alice_Chen1"}]})
    monkeypatch.setattr(
        "app.core.openreview.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(response=response, **kw),
    )

    assert await profile_exists("~Alice_Chen1") is True


async def test_profile_exists_returns_false_for_empty_profiles(monkeypatch):
    response = _FakeResponse(200, {"profiles": []})
    monkeypatch.setattr(
        "app.core.openreview.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(response=response, **kw),
    )

    assert await profile_exists("~Ghost_User1") is False


async def test_profile_exists_returns_false_for_404(monkeypatch):
    response = _FakeResponse(404, {})
    monkeypatch.setattr(
        "app.core.openreview.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(response=response, **kw),
    )

    assert await profile_exists("~Missing_Person1") is False


async def test_profile_exists_raises_on_5xx(monkeypatch):
    response = _FakeResponse(503, {})
    monkeypatch.setattr(
        "app.core.openreview.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(response=response, **kw),
    )

    with pytest.raises(OpenReviewUnavailableError):
        await profile_exists("~Alice_Chen1")


async def test_profile_exists_raises_on_network_error(monkeypatch):
    monkeypatch.setattr(
        "app.core.openreview.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(
            raise_exc=httpx.ConnectError("boom"), **kw,
        ),
    )

    with pytest.raises(OpenReviewUnavailableError):
        await profile_exists("~Alice_Chen1")


async def test_profile_exists_raises_on_timeout(monkeypatch):
    monkeypatch.setattr(
        "app.core.openreview.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(
            raise_exc=httpx.TimeoutException("timeout"), **kw,
        ),
    )

    with pytest.raises(OpenReviewUnavailableError):
        await profile_exists("~Alice_Chen1")
