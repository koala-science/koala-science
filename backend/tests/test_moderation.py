"""Unit tests for the Gemini-backed comment moderation client."""
import json

import httpx
import pytest

from app.core import moderation as moderation_module
from app.core.moderation import (
    ModerationCategory,
    ModerationUnavailableError,
    ModerationVerdict,
    moderate_comment,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict | str):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, str):
            raise json.JSONDecodeError("not json", self._body, 0)
        return self._body


class _FakeAsyncClient:
    def __init__(self, response=None, raise_exc: Exception | None = None, **_):
        self._response = response
        self._raise_exc = raise_exc
        self.sent_headers: dict | None = None
        self.sent_json: dict | None = None
        self.sent_url: str | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url: str, json=None, headers=None):
        self.sent_url = url
        self.sent_json = json
        self.sent_headers = headers
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


def _gemini_payload(verdict: str, category: str, reason: str) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "verdict": verdict,
                                    "category": category,
                                    "reason": reason,
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }


def _patch_httpx(monkeypatch, response=None, raise_exc: Exception | None = None):
    holder = {}

    def factory(**kw):
        client = _FakeAsyncClient(response=response, raise_exc=raise_exc, **kw)
        holder["client"] = client
        return client

    monkeypatch.setattr(moderation_module.httpx, "AsyncClient", factory)
    return holder


@pytest.fixture(autouse=True)
def _stub_gemini_key(monkeypatch):
    monkeypatch.setattr(moderation_module.settings, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(
        moderation_module.settings, "GEMINI_MODERATION_MODEL", "gemini-2.5-flash"
    )


async def test_pass_verdict(monkeypatch):
    response = _FakeResponse(
        200, _gemini_payload("pass", "ok", "substantive engagement")
    )
    holder = _patch_httpx(monkeypatch, response=response)

    result = await moderate_comment(
        "This paper's ablation misses the batch-norm interaction.",
        paper_title="A Study",
    )

    assert result.verdict == ModerationVerdict.PASS
    assert result.category == ModerationCategory.OK
    assert result.reason == "substantive engagement"
    client = holder["client"]
    assert client.sent_headers == {"x-goog-api-key": "fake-key"}
    assert "gemini-2.5-flash" in client.sent_url
    assert ":generateContent" in client.sent_url
    # Body carries the paper title and system prompt.
    assert client.sent_json["systemInstruction"]["parts"][0]["text"].startswith(
        "You moderate comments on Koala Science"
    )
    user_text = client.sent_json["contents"][0]["parts"][0]["text"]
    assert "Paper title: A Study" in user_text
    assert client.sent_json["generationConfig"]["response_mime_type"] == "application/json"


@pytest.mark.parametrize(
    "category",
    [
        "off_topic",
        "low_effort",
        "personal_attack",
        "hate_or_slurs",
        "spam_or_nonsense",
    ],
)
async def test_violate_verdict_each_category(monkeypatch, category):
    response = _FakeResponse(
        200, _gemini_payload("violate", category, "reason text")
    )
    _patch_httpx(monkeypatch, response=response)

    result = await moderate_comment("some comment")

    assert result.verdict == ModerationVerdict.VIOLATE
    assert result.category.value == category


async def test_http_500_raises_unavailable(monkeypatch):
    response = _FakeResponse(500, {"error": "internal"})
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_http_429_raises_unavailable(monkeypatch):
    response = _FakeResponse(429, {"error": "rate"})
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_http_400_raises_unavailable(monkeypatch):
    response = _FakeResponse(400, {"error": "bad"})
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_timeout_raises_unavailable(monkeypatch):
    _patch_httpx(monkeypatch, raise_exc=httpx.TimeoutException("timeout"))

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_network_error_raises_unavailable(monkeypatch):
    _patch_httpx(monkeypatch, raise_exc=httpx.ConnectError("boom"))

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_malformed_json_in_parts_text_raises(monkeypatch):
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "not-json {{{"}]}}
        ]
    }
    response = _FakeResponse(200, payload)
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_missing_candidates_raises(monkeypatch):
    response = _FakeResponse(200, {"candidates": []})
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_verdict_category_mismatch_raises(monkeypatch):
    response = _FakeResponse(
        200, _gemini_payload("pass", "off_topic", "inconsistent")
    )
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_violate_with_ok_category_raises(monkeypatch):
    response = _FakeResponse(
        200, _gemini_payload("violate", "ok", "inconsistent")
    )
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_unknown_enum_value_raises(monkeypatch):
    response = _FakeResponse(
        200, _gemini_payload("maybe", "ok", "whatever")
    )
    _patch_httpx(monkeypatch, response=response)

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")


async def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(moderation_module.settings, "GEMINI_API_KEY", "")

    with pytest.raises(ModerationUnavailableError):
        await moderate_comment("hello")
