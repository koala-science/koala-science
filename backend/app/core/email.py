"""Outbound email via Resend.

Unset ``RESEND_API_KEY`` means log and return. That is what dev, CI and the test
suite run on, so nothing here reaches the network unless a key is configured.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
REQUEST_TIMEOUT_SECONDS = 10.0


class EmailSendError(Exception):
    """Resend refused the message."""


async def send_email(*, to: str, subject: str, html: str, text: str) -> None:
    if not settings.RESEND_API_KEY:
        # Warning rather than info on purpose: an unconfigured sender means real
        # mail is silently not going out, and at INFO this line does not reach
        # uvicorn's handlers — leaving a developer with no way to find the link.
        logger.warning(
            "email NOT SENT (RESEND_API_KEY unset) to=%s subject=%s\n%s",
            to, subject, text,
        )
        return

    payload = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                RESEND_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            )
    except httpx.HTTPError as exc:
        raise EmailSendError(f"Resend request failed: {exc}") from exc

    if response.status_code >= 300:
        raise EmailSendError(
            f"Resend returned {response.status_code}: {response.text[:200]}"
        )
