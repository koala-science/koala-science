"""Tests for the `validity` check — is the argument shaped like an argument?

Three arms: the claim is atomic, the evidence bears on the claim, and the
evidence contains something anyone could go and check.
"""
from types import SimpleNamespace

import pytest

from app.core import checks
from app.models.platform import ArgumentPosition
from app.core.check_runner import CHECK_FUNCTIONS, missing_check_functions
from app.core.checks_validity import (
    ValidityCategory,
    ValidityResult,
    ValidityVerdict,
    validity_check,
)
from app.core.gemini import CheckUnavailableError


class _Argument:
    def __init__(self, claim="A claim.", evidence="Section 4 reports it."):
        self.claim = claim
        self.evidence = evidence
        self.position = ArgumentPosition.NEGATIVE
        self.paper = SimpleNamespace(title="A paper")


def _result(verdict, category, reason="because"):
    return ValidityResult(verdict=verdict, category=category, reason=reason)


def test_registered_in_both_registries():
    assert checks.CHECKS["validity"] == "v1"
    assert "validity" in CHECK_FUNCTIONS
    assert missing_check_functions() == set()


async def test_pass_returns_true(monkeypatch):
    async def _ok(argument_text, *, paper_title=None):
        return _result(ValidityVerdict.PASS, ValidityCategory.OK)

    monkeypatch.setattr("app.core.checks_validity._classify", _ok)
    passed, detail = await validity_check(None, _Argument())
    assert passed is True
    assert detail == "ok"


@pytest.mark.parametrize(
    "category",
    [
        ValidityCategory.NOT_ATOMIC,
        ValidityCategory.EVIDENCE_UNRELATED,
        ValidityCategory.EVIDENCE_UNVERIFIABLE,
    ],
)
async def test_each_arm_fails_with_its_category(monkeypatch, category):
    async def _violates(argument_text, *, paper_title=None):
        return _result(ValidityVerdict.VIOLATE, category, "the reason")

    monkeypatch.setattr("app.core.checks_validity._classify", _violates)
    passed, detail = await validity_check(None, _Argument())
    assert passed is False
    assert category.value in detail
    assert "the reason" in detail


async def test_outage_raises_so_the_row_stays_pending(monkeypatch):
    async def _down(argument_text, *, paper_title=None):
        raise CheckUnavailableError("Gemini returned 503")

    monkeypatch.setattr("app.core.checks_validity._classify", _down)
    with pytest.raises(CheckUnavailableError):
        await validity_check(None, _Argument())


async def test_claim_and_evidence_are_both_sent(monkeypatch):
    seen = {}

    async def _capture(argument_text, *, paper_title=None):
        seen["text"] = argument_text
        return _result(ValidityVerdict.PASS, ValidityCategory.OK)

    monkeypatch.setattr("app.core.checks_validity._classify", _capture)
    await validity_check(None, _Argument(claim="Baseline missing.", evidence="Table 2 omits it."))
    assert "Baseline missing." in seen["text"]
    assert "Table 2 omits it." in seen["text"]


async def test_pass_with_a_non_ok_category_is_treated_as_unusable(monkeypatch):
    """A pass paired with a failure category means the model contradicted itself."""
    from app.core.checks_validity import _parse

    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "pass", "category": "not_atomic", "reason": "x"})


async def test_violate_with_ok_category_is_treated_as_unusable():
    from app.core.checks_validity import _parse

    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "violate", "category": "ok", "reason": "x"})


def test_unknown_category_is_treated_as_unusable():
    from app.core.checks_validity import _parse

    with pytest.raises(CheckUnavailableError):
        _parse({"verdict": "violate", "category": "invented", "reason": "x"})
