"""Wiring tests — assert each hardened write endpoint carries the expected
SlowAPI limit. Introspects ``limiter._route_limits`` (keyed by
``f"{module}.{qualname}"``) rather than exercising the limiter at runtime,
since the test harness disables the limiter (see ``conftest.py``)."""
import pytest

from app.core.rate_limit import (
    AUTH_RATE_LIMIT,
    PAPER_SUBMIT_RATE_LIMIT,
    VERDICT_RATE_LIMIT,
    limiter,
)
from app.api.v1.endpoints import auth as auth_module
from app.api.v1.endpoints import papers as papers_module
from app.api.v1.endpoints import verdicts as verdicts_module


def _registered_limits(func) -> list[str]:
    key = f"{func.__module__}.{func.__name__}"
    return [str(lim.limit) for lim in limiter._route_limits.get(key, [])]


def _limit_matches(registered: list[str], expected: str) -> bool:
    count, _, period = expected.partition("/")
    needle = f"{count} per 1 {period}"
    return any(needle in r for r in registered)


@pytest.mark.parametrize(
    "func, expected",
    [
        (auth_module.signup, AUTH_RATE_LIMIT),
        (auth_module.login, AUTH_RATE_LIMIT),
        (auth_module.agent_key_login, AUTH_RATE_LIMIT),
        (auth_module.refresh_access_token, AUTH_RATE_LIMIT),
    ],
)
def test_auth_endpoints_have_auth_rate_limit(func, expected):
    registered = _registered_limits(func)
    assert registered, f"no limit registered on {func.__module__}.{func.__name__}"
    assert _limit_matches(registered, expected), (
        f"{func.__name__} limits={registered!r} expected contains {expected!r}"
    )


def test_create_paper_has_submit_rate_limit():
    registered = _registered_limits(papers_module.create_paper)
    assert registered, "no limit registered on papers.create_paper"
    assert _limit_matches(registered, PAPER_SUBMIT_RATE_LIMIT), (
        f"create_paper limits={registered!r} expected contains {PAPER_SUBMIT_RATE_LIMIT!r}"
    )


def test_post_verdict_has_verdict_rate_limit():
    registered = _registered_limits(verdicts_module.post_verdict)
    assert registered, "no limit registered on verdicts.post_verdict"
    assert _limit_matches(registered, VERDICT_RATE_LIMIT), (
        f"post_verdict limits={registered!r} expected contains {VERDICT_RATE_LIMIT!r}"
    )
