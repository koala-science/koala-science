"""Shared Gemini plumbing for the argument checks.

Each check supplies its own system prompt and response schema; the request,
the transport errors and the JSON extraction are the same for all of them.

Every failure mode raises ``CheckUnavailableError``. The check runner treats a
raising check as *not done yet* and leaves the row pending, so an outage costs
latency rather than failing an argument — and, under the points economy, rather
than costing its author a point.
"""
import json
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_SECONDS = 10.0


class CheckUnavailableError(Exception):
    """Gemini was unreachable, errored, or returned something unusable."""


async def classify(system_prompt: str, response_schema: dict, user_text: str) -> dict:
    """Run one structured classification. Returns the parsed JSON object."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise CheckUnavailableError("GEMINI_API_KEY is not configured")

    url = f"{GEMINI_API_URL}/models/{settings.GEMINI_MODERATION_MODEL}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
    except httpx.HTTPError as exc:
        raise CheckUnavailableError(f"Gemini request failed: {exc}") from exc

    if response.status_code >= 400:
        raise CheckUnavailableError(f"Gemini returned {response.status_code}")

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise CheckUnavailableError(f"Gemini returned non-JSON body: {exc}") from exc

    candidates = payload.get("candidates")
    if not candidates:
        raise CheckUnavailableError("no candidates in Gemini response")
    parts = candidates[0].get("content", {}).get("parts")
    if not parts:
        raise CheckUnavailableError("no parts in Gemini response")
    text = parts[0].get("text")
    if not text:
        raise CheckUnavailableError("empty text in Gemini response")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckUnavailableError(f"malformed JSON in Gemini response: {exc}") from exc
