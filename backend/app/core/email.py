import logging
import re

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class EmailSendError(RuntimeError):
    pass


def _html_to_text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


async def send_email(to: str, subject: str, html: str) -> None:
    if not settings.RESEND_API_KEY:
        logger.info(
            "send_email no-op (RESEND_API_KEY unset). to=%s subject=%s body=%s",
            to,
            subject,
            html,
        )
        return

    payload = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": _html_to_text(html),
    }
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers,
        )

    if resp.status_code >= 300:
        raise EmailSendError(
            f"Resend API returned {resp.status_code}: {resp.text}"
        )
