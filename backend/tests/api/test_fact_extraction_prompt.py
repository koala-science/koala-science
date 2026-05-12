"""Unit tests for ``scripts.fact_extraction_prompt.parse_facts``.

Pure-Python tests — no DB, no network. Lives under ``tests/api`` because
the spec asks for it there; the parser itself is offline-only.
"""
from scripts.fact_extraction_prompt import (
    PROMPT_VERSION,
    USER_PROMPT_TEMPLATE,
    parse_facts,
)


def test_parse_facts_handles_single_fact():
    raw = "[FACT]: The paper proposes a new attention mechanism."
    assert parse_facts(raw) == [
        "The paper proposes a new attention mechanism."
    ]


def test_parse_facts_handles_multiple_facts():
    raw = (
        "[FACT]: The authors evaluate on three datasets.\n"
        "[FACT]: The reported accuracy is 92.3%.\n"
        "[FACT]: The method is called Foo."
    )
    assert parse_facts(raw) == [
        "The authors evaluate on three datasets.",
        "The reported accuracy is 92.3%.",
        "The method is called Foo.",
    ]


def test_parse_facts_handles_no_facts_sentinel():
    assert parse_facts("[NO FACTS]") == []


def test_parse_facts_handles_no_facts_sentinel_with_whitespace():
    assert parse_facts("  [NO FACTS]\n") == []


def test_parse_facts_handles_empty_response():
    assert parse_facts("") == []
    assert parse_facts("   \n  ") == []


def test_parse_facts_ignores_junk_lines():
    raw = (
        "Here are the facts I extracted:\n"
        "[FACT]: Claim one.\n"
        "Some commentary that the model emitted.\n"
        "[FACT]: Claim two.\n"
        "\n"
        "Done."
    )
    assert parse_facts(raw) == ["Claim one.", "Claim two."]


def test_parse_facts_strips_whitespace_within_fact_text():
    raw = "[FACT]:    A claim with leading whitespace.   "
    assert parse_facts(raw) == ["A claim with leading whitespace."]


def test_parse_facts_keeps_duplicate_fact_texts():
    raw = (
        "[FACT]: Same claim.\n"
        "[FACT]: Same claim."
    )
    assert parse_facts(raw) == ["Same claim.", "Same claim."]


def test_parse_facts_skips_empty_fact_lines():
    raw = "[FACT]:   \n[FACT]: Real claim."
    assert parse_facts(raw) == ["Real claim."]


def test_user_prompt_template_has_required_placeholders():
    formatted = USER_PROMPT_TEMPLATE.format(
        agent_name="agent-foo",
        paper_title="A Title",
        comment_text="some comment body",
    )
    assert "agent-foo" in formatted
    assert "A Title" in formatted
    assert "some comment body" in formatted


def test_prompt_version_is_set():
    """PROMPT_VERSION must be a non-empty short string. Bump it whenever
    the prompt body changes so old extractions don't get overwritten."""
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION
    assert len(PROMPT_VERSION) <= 16
