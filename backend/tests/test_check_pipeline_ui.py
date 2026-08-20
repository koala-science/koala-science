"""The pipeline the UI draws must be the pipeline that runs.

The argument card renders one icon per check, in order, including stages an
argument has not reached — which it cannot derive from the argument alone,
because checks are queued lazily and a fresh argument carries a single row. So
the frontend hardcodes the list.

That is a second copy of something ``CHECKS`` already owns, and the failure mode
is silent: add a fifth check and the rail keeps rendering four, showing an
argument as fully checked while a stage is missing. This is the guard.
"""
import re
from pathlib import Path

from app.core.checks import CHECKS

ARGUMENT_SECTION = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "components" / "paper" / "argument-section.tsx"
)


def _frontend_pipeline() -> list[str]:
    source = ARGUMENT_SECTION.read_text()
    match = re.search(r"const PIPELINE = \[(.*?)\] as const;", source, re.S)
    assert match, f"no PIPELINE literal found in {ARGUMENT_SECTION}"
    return re.findall(r"'([^']+)'", match.group(1))


def test_the_ui_pipeline_matches_the_registry():
    """Same names, same order — the rail is drawn left to right in running order."""
    assert _frontend_pipeline() == list(CHECKS)
