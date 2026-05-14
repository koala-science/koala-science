import logging

import pytest

from app.core import email as email_module
from app.core.email import EmailSendError, send_email


async def test_send_email_noops_without_api_key(monkeypatch, caplog):
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(
        email_module.settings, "RESEND_FROM_EMAIL", "no-reply@example.com"
    )

    called = {"hit": False}

    class _ShouldNotBeCalledClient:
        def __init__(self, *args, **kwargs):
            called["hit"] = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(email_module.httpx, "AsyncClient", _ShouldNotBeCalledClient)

    with caplog.at_level(logging.INFO, logger="app.core.email"):
        await send_email("to@example.com", "subj", "<p>hi</p>")

    assert called["hit"] is False
    assert any("to@example.com" in rec.getMessage() for rec in caplog.records)


async def test_send_email_posts_to_resend_with_bearer(monkeypatch):
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "test_key_123")
    monkeypatch.setattr(
        email_module.settings, "RESEND_FROM_EMAIL", "from@example.com"
    )

    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"id": "abc"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(email_module.httpx, "AsyncClient", _FakeClient)

    await send_email("to@example.com", "Verify your email", "<a>link</a>")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer test_key_123"
    assert captured["json"]["from"] == "from@example.com"
    assert captured["json"]["to"] == ["to@example.com"]
    assert captured["json"]["subject"] == "Verify your email"
    assert captured["json"]["html"] == "<a>link</a>"
    assert "text" in captured["json"]


async def test_send_email_raises_on_non_2xx(monkeypatch):
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "test_key")
    monkeypatch.setattr(
        email_module.settings, "RESEND_FROM_EMAIL", "from@example.com"
    )

    class _Resp:
        status_code = 422
        text = "bad request"

        def json(self):
            return {"message": "invalid"}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json, headers):
            return _Resp()

    monkeypatch.setattr(email_module.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(EmailSendError):
        await send_email("to@example.com", "s", "<p>h</p>")
