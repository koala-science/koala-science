"""The models agents may call through the proxy, what they cost, and the clamps
that bound any one call's cost.

Money is integer micro-dollars throughout ($1 = 1_000_000), and every cost rounds
up: a fraction of a micro-dollar is charged as a whole one.
"""
import json
from dataclasses import dataclass

MICRO_PER_MILLION_TOKENS = 1_000_000

MAX_OUTPUT_TOKENS = 8192
MAX_THINKING_TOKENS = 8192

# No text token is shorter than a byte (digits tokenise one per byte), so text
# never holds more input tokens than the body has bytes. Media does not follow
# bytes at all — a 100-byte image is hundreds of tokens, a small compressed
# video can be a million — so a body with any inline media reserves the whole
# context window.
MAX_INPUT_TOKENS = 1_048_576

ALLOWED_TOOL_KEYS = {"functionDeclarations"}


class RequestRejected(ValueError):
    """A request the proxy will not forward: malformed, or able to cost more
    than its reservation covers."""


@dataclass(frozen=True)
class ModelPrice:
    """Micro-dollars per million tokens. Cached input is part of the prompt
    count but billed at its own rate; thinking is billed as output."""

    input: int
    cached_input: int
    output: int


# One fixed model, so agents know exactly what answers them. It is the model
# Gemini CLI 0.60 sends its flash requests as, so the CLI works once its model
# is pinned, and the SDKs work as they are.
# Paid-tier standard prices from https://ai.google.dev/gemini-api/docs/pricing,
# as published on 2026-10-07. Adding a model is one entry here.
MODELS: dict[str, ModelPrice] = {
    "gemini-3.5-flash": ModelPrice(input=1_500_000, cached_input=150_000, output=9_000_000),
}


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def usage_cost(price: ModelPrice, usage: dict) -> int:
    """The cost of a call from the ``usageMetadata`` Google returned."""
    prompt = usage.get("promptTokenCount", 0)
    cached = usage.get("cachedContentTokenCount", 0)
    tool_prompt = usage.get("toolUsePromptTokenCount", 0)
    output = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    total = (
        (prompt - cached + tool_prompt) * price.input
        + cached * price.cached_input
        + output * price.output
    )
    return _ceil_div(total, MICRO_PER_MILLION_TOKENS)


def encode(body: dict) -> bytes:
    return json.dumps(body, separators=(",", ":")).encode()


def reservation(price: ModelPrice, body: dict) -> int:
    """The most a call with this clamped body can cost."""
    has_media = any("inlineData" in part for part in _parts(body))
    input_tokens = MAX_INPUT_TOKENS if has_media else min(len(encode(body)), MAX_INPUT_TOKENS)
    total = (
        input_tokens * price.input
        + (MAX_OUTPUT_TOKENS + MAX_THINKING_TOKENS) * price.output
    )
    return _ceil_div(total, MICRO_PER_MILLION_TOKENS)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _list(value, name: str) -> list:
    if not isinstance(value, list):
        raise RequestRejected(f"{name} must be a list")
    return value


def _parts(body: dict) -> list:
    """Every part in the conversation and the system instruction."""
    parts = []
    for content in _list(body.get("contents", []), "contents"):
        if not isinstance(content, dict):
            raise RequestRejected("each entry in contents must be an object")
        parts += _list(content.get("parts", []), "parts")
    system = body.get("systemInstruction", {})
    if not isinstance(system, dict):
        raise RequestRejected("systemInstruction must be an object")
    parts += _list(system.get("parts", []), "systemInstruction parts")
    if not all(isinstance(part, dict) for part in parts):
        raise RequestRejected("each part must be an object")
    return parts


def clamp(body) -> dict:
    """Bound what the call can cost, so its reservation covers it.

    Output and thinking are capped, and a missing or dynamic (-1) thinking
    budget becomes the cap rather than whatever the model likes. A thinking
    level is dropped: Google refuses a level and a budget together, and only
    the budget is a bound. One candidate, because the caps apply per candidate.
    Tools other than function declarations, and file references, are refused:
    search is billed per request, and URL context, code execution and a file
    URI all bring in input the body does not contain.
    """
    if not isinstance(body, dict):
        raise RequestRejected("Request body must be a JSON object")
    config = body.get("generationConfig", {})
    if not isinstance(config, dict):
        raise RequestRejected("generationConfig must be an object")
    thinking = config.get("thinkingConfig", {})
    if not isinstance(thinking, dict):
        raise RequestRejected("thinkingConfig must be an object")
    max_output = config.get("maxOutputTokens", MAX_OUTPUT_TOKENS)
    budget = thinking.get("thinkingBudget", -1)
    if not (_is_int(max_output) and _is_int(budget)):
        raise RequestRejected("maxOutputTokens and thinkingBudget must be integers")

    for tool in _list(body.get("tools", []), "tools"):
        if not isinstance(tool, dict) or set(tool) - ALLOWED_TOOL_KEYS:
            raise RequestRejected(
                "Only function declarations are allowed as tools: search, URL context "
                "and code execution are billed outside the model credit"
            )
    if any("fileData" in part for part in _parts(body)):
        raise RequestRejected("File references (fileData) are not allowed; send the content inline")

    thinking = {
        **{k: v for k, v in thinking.items() if k != "thinkingLevel"},
        "thinkingBudget": MAX_THINKING_TOKENS if budget < 0 else min(budget, MAX_THINKING_TOKENS),
    }
    config = {
        **config,
        "maxOutputTokens": min(max_output, MAX_OUTPUT_TOKENS),
        "candidateCount": 1,
        "thinkingConfig": thinking,
    }
    return {**body, "generationConfig": config}
