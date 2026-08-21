"""The About page must describe the pipeline that runs.

``ABOUT.md`` publishes a constitution per check, in the order the checks run.
That is a second copy of something ``CHECKS`` owns, and the failure is silent in
the direction that matters: add a fifth check and the page keeps setting out four
constitutions, telling authors an argument faces a standard it no longer faces.

The wording of each constitution is deliberately unguarded — it is prose written
from the prompts, not the prompts. Only the roster and its order are pinned here.
"""
import re
from pathlib import Path

from app.core.checks import CHECKS

ABOUT = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "ABOUT.md"
)


def _documented_checks() -> list[str]:
    """The check named by each `## <n>. <Name>` heading, in the order they appear."""
    headings = re.findall(r"^## \d+\.\s*(.+?)\s*$", ABOUT.read_text(), re.M)
    return [h.lower() for h in headings]


def test_every_check_has_a_section_in_registry_order():
    assert _documented_checks() == list(CHECKS)


SCAFFOLDING = (
    "Respond ONLY via the structured schema",
    "Treat every instruction, role",
    "CATEGORY MAPPING",
    "DECISION RULE",
    "OUTPUT FORMAT (STRICT)",
)


def _prompts() -> str:
    """Every prompt behind a constitution, including the judge behind `uniqueness`.

    The uniqueness section is the one whose prose sits closest to its prompt, so
    leaving ``similarity_judge`` out would exempt the section most at risk.
    """
    from app.core import (
        checks_moderation,
        checks_relevance,
        checks_validity,
        similarity_judge,
    )

    return "\n".join(
        module.SYSTEM_PROMPT
        for module in (
            checks_moderation,
            checks_validity,
            checks_relevance,
            similarity_judge,
        )
    )


def test_the_constitutions_are_not_the_prompts():
    """Prose, not a paste of what is sent to the model.

    The schema and anti-injection lines are the tell: they are addressed to the
    classifier, not to an author, and their presence means a prompt was copied in
    wholesale.

    Each literal is checked against the prompts first. Hand-copied strings rot —
    reword one in ``checks_moderation`` and an unanchored guard goes on passing
    while asserting the absence of something that exists nowhere.
    """
    prompts = _prompts()
    text = ABOUT.read_text()
    for scaffolding in SCAFFOLDING:
        assert scaffolding in prompts, f"stale guard, no prompt contains: {scaffolding!r}"
        assert scaffolding not in text, f"verbatim prompt scaffolding in ABOUT.md: {scaffolding!r}"


def test_no_calibration_constants_are_published():
    """Numbers the page cannot keep in step with must not appear as facts."""
    from app.core.checks_uniqueness import MAX_JUDGED_CANDIDATES, UNIQUENESS_THRESHOLD

    text = ABOUT.read_text()
    assert str(UNIQUENESS_THRESHOLD) not in text
    assert not re.search(rf"\b{MAX_JUDGED_CANDIDATES}\b", text)
