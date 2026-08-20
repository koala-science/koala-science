"""Shared Gemini plumbing for the argument checks.

Each check supplies its own system prompt, and either a response schema
(``classify``) or nothing (``judge``); the request, the transport errors
and the response unwrapping are the same for all of them.

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

# The similarity judge reasons through a long taxonomy before answering, so it
# needs considerably longer than a one-shot structured classification. Its model
# is named here rather than borrowed from GEMINI_MODERATION_MODEL: the judge is a
# carried-over calibration, and retuning moderation must not silently move it.
JUDGE_TIMEOUT_SECONDS = 60.0
JUDGE_MODEL = "gemini-2.5-flash"


class CheckUnavailableError(Exception):
    """Gemini was unreachable, errored, or returned something unusable."""


async def _generate(
    system_prompt: str,
    user_text: str,
    generation_config: dict,
    timeout: float,
    model: str,
) -> str:
    """POST one request and return the candidate's text. Raises on anything else."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise CheckUnavailableError("GEMINI_API_KEY is not configured")

    url = f"{GEMINI_API_URL}/models/{model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": generation_config,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
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
    return text


async def classify(system_prompt: str, response_schema: dict, user_text: str) -> dict:
    """Run one structured classification. Returns the parsed JSON object."""
    text = await _generate(
        system_prompt,
        user_text,
        {"response_mime_type": "application/json", "response_schema": response_schema},
        TIMEOUT_SECONDS,
        settings.GEMINI_MODERATION_MODEL,
    )

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckUnavailableError(f"malformed JSON in Gemini response: {exc}") from exc


async def judge(system_prompt: str, user_text: str) -> str:
    """Run one similarity judgement. Returns the raw response text.

    The judge cannot use ``classify``: it was calibrated reasoning step by step
    and then emitting a label, and a response schema removes the reasoning the
    label depends on.
    """
    return await _generate(
        system_prompt, user_text, {"temperature": 0.0}, JUDGE_TIMEOUT_SECONDS, JUDGE_MODEL
    )
