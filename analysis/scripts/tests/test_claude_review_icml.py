import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import claude_review_icml
from claude_review_icml import out_path
from icml_review_prompt import ICMLReview

_REVIEW = ICMLReview(summary="s", strengths_and_weaknesses="w", soundness=3,
                     presentation=3, significance=3, originality=3,
                     key_questions_for_authors="q", limitations="l",
                     overall_recommendation=4, confidence=3)


async def _fake_review_one(client, model, paper) -> dict:
    return {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model, "status": "ok",
            "review": {"overall_recommendation": 4},
            "usage": {"input": 1, "output": 1}}


def test_out_path_is_model_specific():
    assert out_path("claude-haiku-4-5").name == "icml_2026_claude_icml_reviews_claude-haiku-4-5.jsonl"
    assert out_path("claude-sonnet-5").name == "icml_2026_claude_icml_reviews_claude-sonnet-5.jsonl"
    assert out_path("claude-haiku-4-5") != out_path("claude-sonnet-5")


def _write(path: Path, paper_ids: list[str]) -> None:
    path.write_text("".join(
        json.dumps({"paper_id": pid, "status": "ok", "review": {}}) + "\n"
        for pid in paper_ids))


def test_refresh_on_a_paper_subset_keeps_the_other_records(tmp_path, monkeypatch):
    """--refresh --paper-ids-file must replace only the named papers. Opening
    the output in "w" mode would drop every review already collected."""
    out = tmp_path / "reviews.jsonl"
    _write(out, ["keep-1", "redo", "keep-2"])

    monkeypatch.setattr(claude_review_icml, "out_path", lambda model: out)
    monkeypatch.setattr(claude_review_icml, "load_papers",
                        lambda paper_ids=None: [{"paper_id": "redo", "forum_id": "f",
                                                 "title": "t", "pdf_uuid": "u"}])
    monkeypatch.setattr(claude_review_icml, "review_one", _fake_review_one)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    asyncio.run(claude_review_icml.run("claude-sonnet-5", 1, None, ["redo"], True))

    rows = [json.loads(l) for l in out.open()]
    assert [r["paper_id"] for r in rows] == ["keep-1", "keep-2", "redo"]
    assert rows[-1]["review"] == {"overall_recommendation": 4}


def test_refresh_over_the_full_set_still_replaces_everything(tmp_path, monkeypatch):
    out = tmp_path / "reviews.jsonl"
    _write(out, ["a", "b"])

    monkeypatch.setattr(claude_review_icml, "out_path", lambda model: out)
    monkeypatch.setattr(claude_review_icml, "load_papers",
                        lambda paper_ids=None: [{"paper_id": p, "forum_id": "f",
                                                 "title": "t", "pdf_uuid": "u"}
                                                for p in ("a", "b")])
    monkeypatch.setattr(claude_review_icml, "review_one", _fake_review_one)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    asyncio.run(claude_review_icml.run("claude-sonnet-5", 1, None, None, True))

    rows = [json.loads(l) for l in out.open()]
    assert sorted(r["paper_id"] for r in rows) == ["a", "b"]
    assert len(rows) == 2


def test_refresh_with_a_limit_keeps_the_papers_beyond_the_limit(tmp_path, monkeypatch):
    """--refresh --limit reviews a prefix of the cohort; the records for the
    papers it never reaches must survive."""
    out = tmp_path / "reviews.jsonl"
    _write(out, ["a", "b"])

    monkeypatch.setattr(claude_review_icml, "out_path", lambda model: out)
    monkeypatch.setattr(claude_review_icml, "load_papers",
                        lambda paper_ids=None: [{"paper_id": p, "forum_id": "f",
                                                 "title": "t", "pdf_uuid": "u"}
                                                for p in ("a", "b")])
    monkeypatch.setattr(claude_review_icml, "review_one", _fake_review_one)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    asyncio.run(claude_review_icml.run("claude-sonnet-5", 1, 1, None, True))

    rows = [json.loads(l) for l in out.open()]
    assert [r["paper_id"] for r in rows] == ["b", "a"]


def test_a_response_truncated_at_the_token_cap_is_not_recorded_as_ok():
    """A max_tokens stop can still parse -- one sonnet-5 paper came back with
    empty required fields and soundness=0. Storing that as ok feeds a verdict
    built from a half-written review into the leaderboards."""
    resp = SimpleNamespace(
        stop_reason="max_tokens",
        content=[SimpleNamespace(type="text", parsed_output=_REVIEW)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=16000))

    with pytest.raises(RuntimeError, match="truncated at the token cap"):
        claude_review_icml.review_from_response(resp)


def test_a_completed_response_yields_its_parsed_review():
    resp = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", parsed_output=_REVIEW)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=4000))

    assert claude_review_icml.review_from_response(resp) is _REVIEW


def test_a_refusal_has_no_parsed_output_and_is_rejected():
    """Sonnet 5 refuses two papers in the cohort; the refusal arrives as a
    stop_reason with no text block rather than as an API error."""
    resp = SimpleNamespace(
        stop_reason="refusal", content=[],
        usage=SimpleNamespace(input_tokens=10, output_tokens=0))

    with pytest.raises(RuntimeError, match="no parsed output"):
        claude_review_icml.review_from_response(resp)
