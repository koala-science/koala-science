"""The pipeline the landing page walks through must be the pipeline that runs.

The section on `/` names each check and describes it in a sentence, in running
order. That is a third copy of what ``CHECKS`` owns — after the argument card's
rail and the constitution document — and the failure is the quiet kind: add a
fifth check and the landing page goes on telling every visitor that an argument
faces four.

Only the roster and its order are pinned. The one-line descriptions are prose,
deliberately unguarded, like the constitutions they summarise.
"""
import re
from pathlib import Path

from app.core.checks import CHECKS

PIPELINE_SECTION = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "components" / "home" / "pipeline.tsx"
)


def _steps_literal() -> str:
    source = PIPELINE_SECTION.read_text()
    match = re.search(r"const STEPS = \[(.*?)\] as const;", source, re.S)
    assert match, f"no STEPS literal found in {PIPELINE_SECTION}"
    return match.group(1)


def _field(name: str) -> list[str]:
    """Values of `name` inside the STEPS literal, in source order.

    Quote style and line breaks are both tolerated: the repo has no formatter
    and no quote-style rule, and a reformat — wrapping a long description onto
    its own line, say — would otherwise fail here with output indistinguishable
    from a real drift.
    """
    return re.findall(rf"{name}:\s*['\"]([^'\"]+)['\"]", _steps_literal())


def test_the_landing_pipeline_matches_the_registry():
    assert _field("key") == list(CHECKS)


def test_every_step_carries_a_description():
    """A named check with no sentence is a step the reader cannot understand."""
    descriptions = _field("description")
    assert len(descriptions) == len(CHECKS)
