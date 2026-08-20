"""Tests for the `moderation` check — the first gate an argument must clear."""
from types import SimpleNamespace

import pytest

from app.core import checks
from app.core.gemini import CheckUnavailableError
from app.models.platform import ArgumentPosition
from app.core.check_runner import CHECK_FUNCTIONS, missing_check_functions
from app.core.checks_moderation import (
    ModerationCategory,
    ModerationResult,
    ModerationVerdict,
    moderation_check,
)


class _Argument:
    """Minimal stand-in — the check only reads these four attributes."""

    def __init__(self, claim="A claim.", evidence="Some evidence."):
        self.claim = claim
        self.evidence = evidence
        self.position = ArgumentPosition.NEGATIVE
        self.paper = SimpleNamespace(title="A paper")


def test_registered_in_both_registries():
    assert checks.CHECKS["moderation"] == "v1"
    assert "moderation" in CHECK_FUNCTIONS
    assert missing_check_functions() == set()


async def test_pass_returns_true_with_the_category(monkeypatch):
    async def _ok(content, *, paper_title=None):
        return ModerationResult(
            verdict=ModerationVerdict.PASS,
            category=ModerationCategory.OK,
            reason="fine",
        )

    monkeypatch.setattr("app.core.checks_moderation._classify", _ok)
    passed, detail = await moderation_check(None, _Argument())
    assert passed is True
    assert detail == "ok"


async def test_violation_returns_false_with_category_and_reason(monkeypatch):
    async def _violates(content, *, paper_title=None):
        return ModerationResult(
            verdict=ModerationVerdict.VIOLATE,
            category=ModerationCategory.LOW_EFFORT,
            reason="no paper-specific point",
        )

    monkeypatch.setattr("app.core.checks_moderation._classify", _violates)
    passed, detail = await moderation_check(None, _Argument())
    assert passed is False
    assert "low_effort" in detail
    assert "no paper-specific point" in detail


async def test_outage_raises_so_the_row_stays_pending(monkeypatch):
    """An outage is not the argument's fault — the runner must retry, not fail it."""

    async def _down(content, *, paper_title=None):
        raise CheckUnavailableError("Gemini returned 503")

    monkeypatch.setattr("app.core.checks_moderation._classify", _down)
    with pytest.raises(CheckUnavailableError):
        await moderation_check(None, _Argument())


async def test_claim_and_evidence_are_both_sent(monkeypatch):
    seen = {}

    async def _capture(content, *, paper_title=None):
        seen["content"] = content
        return ModerationResult(
            verdict=ModerationVerdict.PASS,
            category=ModerationCategory.OK,
            reason="fine",
        )

    monkeypatch.setattr("app.core.checks_moderation._classify", _capture)
    await moderation_check(None, _Argument(claim="The baseline is missing.", evidence="Table 2."))
    assert "The baseline is missing." in seen["content"]
    assert "Table 2." in seen["content"]
