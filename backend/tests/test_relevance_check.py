"""Tests for the `relevance` check — does the argument bear on accept/reject?

Unlike moderation and validity this check is a disjunction: three routes, and
taking any one is enough. These cover the plumbing — registration, the pass and
fail paths, the outage contract, and what reaches the model. Whether the prompt
draws the line in the right place is measured by ``evals/run_relevance.py``,
which needs a live key and so cannot live here.
"""
from types import SimpleNamespace

import pytest

from app.core import checks
from app.core.check_runner import CHECK_FUNCTIONS, missing_check_functions
from app.core.checks_relevance import (
    RelevanceCategory,
    RelevanceResult,
    RelevanceVerdict,
    relevance_check,
)
from app.core.gemini import CheckUnavailableError
from app.models.platform import ArgumentPosition


class _Argument:
    def __init__(self, claim="A claim.", evidence="Section 4 reports it.",
                 position=ArgumentPosition.NEGATIVE):
        self.claim = claim
        self.evidence = evidence
        self.position = position
        self.paper = SimpleNamespace(title="A paper", abstract="An abstract.")


def _result(verdict, category, reason="because"):
    return RelevanceResult(verdict=verdict, category=category, reason=reason)


def test_registered_in_both_registries():
    assert checks.CHECKS["relevance"] == "v1"
    assert "relevance" in CHECK_FUNCTIONS
    assert missing_check_functions() == set()


def test_runs_after_validity_and_before_uniqueness():
    """Cheap per-argument gates first; the cross-argument one last. An argument
    that does not bear on the decision should never become something a later
    argument can collide with."""
    order = list(checks.CHECKS)
    assert order.index("validity") < order.index("relevance") < order.index("uniqueness")


async def test_pass_returns_true(monkeypatch):
    async def _ok(argument_text, *, paper_title=None, paper_abstract=None):
        return _result(RelevanceVerdict.PASS, RelevanceCategory.OK)

    monkeypatch.setattr("app.core.checks_relevance._classify", _ok)
    passed, detail = await relevance_check(None, _Argument())
    assert passed is True
    assert detail == "ok"


@pytest.mark.parametrize("category", [
    RelevanceCategory.COSMETIC,
    RelevanceCategory.TRIVIAL,
    RelevanceCategory.UNSUBSTANTIVE_PRAISE,
])
async def test_each_category_fails_with_its_reason(monkeypatch, category):
    async def _violates(argument_text, *, paper_title=None, paper_abstract=None):
        return _result(RelevanceVerdict.VIOLATE, category, "the reason")

    monkeypatch.setattr("app.core.checks_relevance._classify", _violates)
    passed, detail = await relevance_check(None, _Argument())
    assert passed is False
    assert category.value in detail
    assert "the reason" in detail


async def test_outage_raises_so_the_row_stays_pending(monkeypatch):
    async def _down(argument_text, *, paper_title=None, paper_abstract=None):
        raise CheckUnavailableError("Gemini returned 503")

    monkeypatch.setattr("app.core.checks_relevance._classify", _down)
    with pytest.raises(CheckUnavailableError):
        await relevance_check(None, _Argument())


async def test_the_abstract_reaches_the_model(monkeypatch):
    """Relevance is judged against what the paper set out to do, so unlike the
    other two checks this one needs the abstract and not just the title."""
    seen = {}

    async def _capture(argument_text, *, paper_title=None, paper_abstract=None):
        seen.update(text=argument_text, title=paper_title, abstract=paper_abstract)
        return _result(RelevanceVerdict.PASS, RelevanceCategory.OK)

    monkeypatch.setattr("app.core.checks_relevance._classify", _capture)
    await relevance_check(None, _Argument(claim="Baseline missing.",
                                          evidence="Table 2 omits it."))
    assert "Baseline missing." in seen["text"]
    assert "Table 2 omits it." in seen["text"]
    assert seen["title"] == "A paper"
    assert seen["abstract"] == "An abstract."


async def test_position_reaches_the_model(monkeypatch):
    """Praise and criticism take different routes, so the model has to know
    which one it is looking at."""
    seen = {}

    async def _capture(argument_text, *, paper_title=None, paper_abstract=None):
        seen["text"] = argument_text
        return _result(RelevanceVerdict.PASS, RelevanceCategory.OK)

    monkeypatch.setattr("app.core.checks_relevance._classify", _capture)
    await relevance_check(None, _Argument(position=ArgumentPosition.POSITIVE))
    assert "positive" in seen["text"]


def test_a_verdict_that_contradicts_its_category_is_unusable():
    """Neither direction is a failure of the argument — treat it as an outage."""
    from app.core.checks_relevance import _parse

    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "pass", "category": "cosmetic", "reason": "r"})
    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "violate", "category": "ok", "reason": "r"})


def test_malformed_response_is_unusable():
    from app.core.checks_relevance import _parse

    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "maybe", "category": "ok", "reason": "r"})
    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "pass", "category": "ok"})
    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "pass", "category": "ok", "reason": 7})


def test_schema_and_enum_agree():
    """The schema is what constrains the model; the enum is what parses it.
    A category in one and not the other is an outage on every occurrence."""
    from app.core.checks_relevance import RESPONSE_SCHEMA

    schema_categories = set(RESPONSE_SCHEMA["properties"]["category"]["enum"])
    assert schema_categories == {c.value for c in RelevanceCategory}
    schema_verdicts = set(RESPONSE_SCHEMA["properties"]["verdict"]["enum"])
    assert schema_verdicts == {v.value for v in RelevanceVerdict}
