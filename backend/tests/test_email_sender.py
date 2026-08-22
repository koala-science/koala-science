"""The sender must not reach the network unless a key is configured.

Dev, CI and the whole test suite run with `RESEND_API_KEY` unset. If that path
ever started making requests, every test run would be posting mail to a third
party.
"""
import httpx
import pytest

from app.core import email as email_module
from app.core.email import EmailSendError, send_email

MESSAGE = dict(to="someone@mila.quebec", subject="s", html="<p>h</p>", text="t")


class _Boom:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *a, **kw):
        raise AssertionError("no HTTP call may be made without an API key")


async def test_no_key_means_no_request(monkeypatch, caplog):
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(email_module.httpx, "AsyncClient", lambda **kw: _Boom())

    await send_email(**MESSAGE)  # must not raise


class _Recorder:
    def __init__(self, status):
        self.status = status
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return httpx.Response(self.status, json={})


async def test_a_key_sends_the_message(monkeypatch):
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email_module.settings, "RESEND_FROM_EMAIL", "no-reply@koala.science")
    recorder = _Recorder(200)
    monkeypatch.setattr(email_module.httpx, "AsyncClient", lambda **kw: recorder)

    await send_email(**MESSAGE)

    url, body, headers = recorder.calls[0]
    assert url == email_module.RESEND_API_URL
    assert body["to"] == ["someone@mila.quebec"]
    assert body["from"] == "no-reply@koala.science"
    assert headers["Authorization"] == "Bearer re_test"


async def test_a_refusal_raises(monkeypatch):
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email_module.httpx, "AsyncClient", lambda **kw: _Recorder(422))

    with pytest.raises(EmailSendError):
        await send_email(**MESSAGE)
