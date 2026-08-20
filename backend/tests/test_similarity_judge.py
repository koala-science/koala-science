"""The shared similarity judge: label parsing and the duplicate mapping.

Pure functions and prompt strings — no database, no network. The analysis
pipeline imports the same module, so these also guard the checkpoint files in
``analysis/data`` that still hold four-way labels.
"""
import pytest

from app.core.similarity_judge import (
    DIFFERENT_ARGUMENT,
    DIFFERENT_SUBJECT,
    SAME_ARGUMENT,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    is_duplicate,
    match_label,
)


@pytest.mark.parametrize("label,expected", [
    (SAME_ARGUMENT, True),
    (DIFFERENT_ARGUMENT, False),
    (DIFFERENT_SUBJECT, False),
    ("same subject, same argument, same evidence", True),
    ("same subject, same argument, different evidence", True),
])
def test_is_duplicate(label, expected):
    """Both legacy evidence outcomes meant duplicate, so dropping the dimension
    left every stored label's meaning unchanged."""
    assert is_duplicate(label) is expected


def test_is_duplicate_rejects_an_unknown_label():
    with pytest.raises(ValueError):
        is_duplicate("probably the same")


def test_answer_tag_after_reasoning():
    response = (
        "Step 1 (Subject). Both items point at Table 2.\n"
        "Step 2 (Argument). Both reduce to 'Table 2 is incomplete'.\n"
        "<answer>same subject, same argument</answer>"
    )
    assert match_label(response) == SAME_ARGUMENT


def test_last_tag_wins():
    """The prompt asks for one tag at the end, but a model that narrates its way
    through the taxonomy can emit an earlier one."""
    response = (
        "A naive reading suggests <answer>different subject</answer>, but on "
        "reflection both items address Figure 3.\n"
        "<answer>same subject, different argument</answer>"
    )
    assert match_label(response) == DIFFERENT_ARGUMENT


def test_legacy_four_way_answer_keeps_its_own_label():
    """Longest-first matching: the three-way labels are prefixes of the legacy
    ones, so a shorter label must not swallow a legacy answer."""
    response = "<answer>same subject, same argument, different evidence</answer>"
    assert match_label(response) == "same subject, same argument, different evidence"


def test_missing_tag_is_none_not_a_verdict():
    """None is 'no answer', which callers must never read as 'not a duplicate'."""
    assert match_label("I think these are the same argument.") is None


def test_tag_tolerates_quotes_and_case():
    assert match_label('<ANSWER>"Different Subject"</ANSWER>') == DIFFERENT_SUBJECT


def test_prompt_has_no_evidence_dimension_left():
    assert "evidence" not in SYSTEM_PROMPT.lower()
    assert "Step 3" not in SYSTEM_PROMPT
    assert "four labels" not in SYSTEM_PROMPT


def test_prompt_keeps_the_calibrated_argument_reduction():
    """The worked example is what teaches the model that different reasons for
    the same flaw are the same argument. Losing it changes the judge."""
    assert "sleep/wake classification is inadequate" in SYSTEM_PROMPT
    assert "X is <FLAW_TYPE>" in SYSTEM_PROMPT


def test_user_template_fills_all_placeholders():
    filled = USER_PROMPT_TEMPLATE.format(
        paper_text="Title: A paper", reviewer_a="alice", reviewer_b="bob",
        item_a="Table 2 omits variance.", item_b="Table 2 has no error bars.",
    )
    assert "{" not in filled
