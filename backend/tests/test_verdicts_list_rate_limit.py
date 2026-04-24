"""Sanity check that GET /verdicts/ has the per-actor rate limit applied.

The test suite disables the limiter globally (``conftest.py`` sets
``limiter.enabled = False``), so an end-to-end 429 test isn't reliable
here. Instead we introspect SlowAPI's route registry, which is the same
structure the middleware consults at request time.
"""
from app.api.v1.endpoints.verdicts import list_verdicts
from app.core.rate_limit import VERDICT_LIST_RATE_LIMIT, limiter


def _route_key(func) -> str:
    return f"{func.__module__}.{func.__qualname__}"


def test_list_verdicts_has_rate_limit_registered():
    """``@limiter.limit(VERDICT_LIST_RATE_LIMIT)`` must be on ``list_verdicts``."""
    key = _route_key(list_verdicts)
    assert key in limiter._route_limits, (
        f"list_verdicts is not registered with the limiter under {key!r}; "
        f"known keys: {list(limiter._route_limits)}"
    )
    limits = limiter._route_limits[key]
    assert limits, f"no limits registered for {key!r}"
    rendered = [str(lim.limit) for lim in limits]
    # SlowAPI renders "30/minute" as "30 per 1 minute".
    assert any("30" in r and "minute" in r for r in rendered), (
        f"expected a 30/minute limit for list_verdicts, got {rendered}"
    )


def test_verdict_list_rate_limit_constant_value():
    """Guard the constant so a refactor can't silently loosen the cap."""
    assert VERDICT_LIST_RATE_LIMIT == "30/minute"
