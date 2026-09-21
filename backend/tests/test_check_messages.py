"""The public face of a check result: plain words, no classifier internals."""
import uuid
from types import SimpleNamespace

import pytest

from app.core.check_messages import GENERIC_SUMMARY, public_check_result
from app.core.checks_moderation import ModerationCategory
from app.core.checks_relevance import RelevanceCategory
from app.core.checks_validity import ValidityCategory
from app.core.checks_verification import Verdict
from app.models.platform import CheckStatus
from app.schemas.platform import ArgumentCheckResponse

DUPLICATE_ID = "6d21b8ed-676b-4d24-9640-3bf7cf59522d"

# Every category a check can write before the colon. A category missing a
# summary would fall through to the generic text — safe, but unhelpful.
FAILURE_CATEGORIES = (
    [("moderation", c.value) for c in ModerationCategory if c.value != "ok"]
    + [("validity", c.value) for c in ValidityCategory if c.value != "ok"]
    + [("relevance", c.value) for c in RelevanceCategory if c.value != "ok"]
    + [("verification", v.value) for v in Verdict if v is not Verdict.VERIFIED]
)


@pytest.mark.parametrize(("name", "category"), FAILURE_CATEGORIES)
def test_every_category_gets_its_own_summary_and_keeps_the_reason(name, category):
    summary, explanation = public_check_result(
        name, "failed", f"{category}: The claim makes two distinct points."
    )
    assert summary != GENERIC_SUMMARY
    assert category not in summary
    assert explanation == "The claim makes two distinct points."


def test_the_reported_page_no_longer_shows_the_category():
    summary, explanation = public_check_result(
        "validity",
        "failed",
        "not_atomic: The claim makes two distinct points: that the paper reports "
        "instances of performance degradation, and that it fails to explain them.",
    )
    assert "not_atomic" not in summary + explanation
    assert explanation.startswith("The claim makes two distinct points")


def test_duplicate_names_the_argument_but_not_the_label_or_score():
    summary, explanation = public_check_result(
        "uniqueness", "failed", f"duplicate of {DUPLICATE_ID} (same subject, same argument, cos=0.814)"
    )
    assert DUPLICATE_ID in explanation
    for internal in ("cos=", "0.814", "same subject"):
        assert internal not in summary + explanation


@pytest.mark.parametrize(
    "detail",
    [
        "manuscript unavailable: the paper's text could not be read",
        "no verdict reached: the evidence took longer than 300s to check",
        "no verdict reached: error_max_budget_usd",
    ],
)
def test_verification_run_failures_hide_their_internals(detail):
    summary, explanation = public_check_result("verification", "failed", detail)
    assert summary and summary != GENERIC_SUMMARY
    assert explanation is None


def test_truncation_note_survives_with_the_reason():
    summary, explanation = public_check_result(
        "verification",
        "failed",
        "unsupported: The table is real. (the stored manuscript is truncated, so "
        "evidence past the cut is unreadable)",
    )
    assert "truncated" in explanation


def test_runner_give_up_is_generic():
    assert public_check_result("verification", "failed", "could not be checked after 3 attempts") == (
        "This check didn't finish.",
        None,
    )


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("validity", "brand_new_category: something internal"),
        ("moderation", "not_atomic: category from a different check"),
        ("some_future_check", "whatever: shape"),
        ("validity", "free text with no category"),
        ("validity", None),
    ],
)
def test_unknown_shapes_say_nothing_specific(name, detail):
    assert public_check_result(name, "failed", detail) == (GENERIC_SUMMARY, None)


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        ("passed", "ok"),
        ("passed", "unique (candidates=3, max_cos=0.712)"),
        ("passed", "The quoted passage appears verbatim in Section 4."),
        ("pending", None),
    ],
)
def test_checks_that_did_not_fail_say_nothing(status, detail):
    assert public_check_result("uniqueness", status, detail) == (None, None)


def _row(name: str, status: CheckStatus, detail: str | None):
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, version="v1", status=status, detail=detail, flag_count=0
    )


def test_response_never_serialises_the_stored_detail():
    response = ArgumentCheckResponse.model_validate(
        _row("validity", CheckStatus.FAILED, "not_atomic: Two points.")
    )
    assert response.summary.startswith("Makes independent claims")
    assert response.detail == "Two points."
    assert "not_atomic" not in response.model_dump_json()


def test_response_hides_passed_detail():
    response = ArgumentCheckResponse.model_validate(
        _row("uniqueness", CheckStatus.PASSED, "unique (candidates=0, max_cos=0.000)")
    )
    assert response.summary is None and response.detail is None


def test_revalidating_a_response_is_stable():
    # FastAPI validates a returned model again against response_model; the
    # public explanation must not be re-parsed as if it were a stored detail.
    first = ArgumentCheckResponse.model_validate(
        _row("validity", CheckStatus.FAILED, "not_atomic: evidence_unrelated: nested")
    )
    again = ArgumentCheckResponse.model_validate(first.model_dump())
    assert (again.summary, again.detail) == (first.summary, first.detail)


def test_response_links_a_duplicate_to_the_earlier_argument():
    response = ArgumentCheckResponse.model_validate(
        _row("uniqueness", CheckStatus.FAILED, f"duplicate of {DUPLICATE_ID} (same argument, cos=0.9)")
    )
    assert str(response.duplicate_of) == DUPLICATE_ID
    again = ArgumentCheckResponse.model_validate(response.model_dump())
    assert again.duplicate_of == response.duplicate_of


def test_only_a_failed_uniqueness_check_links_anywhere():
    for name, status in (("uniqueness", CheckStatus.PASSED), ("validity", CheckStatus.FAILED)):
        response = ArgumentCheckResponse.model_validate(
            _row(name, status, f"duplicate of {DUPLICATE_ID} (x, cos=0.9)")
        )
        assert response.duplicate_of is None
