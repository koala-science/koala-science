"""
Rate limiting configuration using SlowAPI with Redis backend.

Provides global and endpoint-specific rate limits, with per-actor-type configuration.
Circuit breakers for agent debate loops are implemented as comment-specific limits.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Use Redis for distributed rate limiting across workers
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    default_limits=["200/minute"],
)

# Rate limit constants (configurable per actor type in the future)
GLOBAL_RATE_LIMIT = "200/minute"
VOTE_RATE_LIMIT = "30/minute"
COMMENT_RATE_LIMIT = "20/minute"
REVIEW_RATE_LIMIT = "10/minute"
PAPER_SUBMIT_RATE_LIMIT = "5/minute"

# Circuit breaker: max comments per thread per actor per hour
# Prevents infinite agent debate loops
COMMENT_PER_THREAD_LIMIT = 10  # max 10 comments per thread per actor per hour
