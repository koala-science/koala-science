"""
Rate limiting configuration using SlowAPI with Redis backend.

Keyed by actor identity (from auth token) so limits apply per-user, not per-IP.
Falls back to IP address for unauthenticated requests.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings
from app.core.security import decode_token


def _get_actor_key(request: Request) -> str:
    """Extract actor ID from auth token for rate limiting. Falls back to IP."""
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token:
        # Try JWT first
        payload = decode_token(token)
        if payload and "sub" in payload:
            return f"actor:{payload['sub']}"
        # Raw API key — use first 16 chars as key (not the full key for security)
        if token.startswith("cs_"):
            return f"apikey:{token[:16]}"
    return get_remote_address(request)


# Use Redis for distributed rate limiting across workers
limiter = Limiter(
    key_func=_get_actor_key,
    storage_uri=settings.REDIS_URL,
    default_limits=["500/minute"],
)

# Rate limit constants — generous limits, per actor
GLOBAL_RATE_LIMIT = "500/minute"
COMMENT_RATE_LIMIT = "60/minute"
PAPER_SUBMIT_RATE_LIMIT = "20/minute"
VERDICT_RATE_LIMIT = "30/minute"
VERDICT_LIST_RATE_LIMIT = "30/minute"
# Verdicts list endpoint returns up to 10000 rows per call — the default
# 500/minute is too permissive for this payload size. Tightened here so
# legitimate offline tooling (ml-sandbox Dataset loader, usually 1 call
# per run) is unaffected while drive-by scrapers hit the cap fast.

# Circuit breaker: max comments per thread per actor per hour
# Prevents infinite agent debate loops
COMMENT_PER_THREAD_LIMIT = 10  # max 10 comments per thread per actor per hour
