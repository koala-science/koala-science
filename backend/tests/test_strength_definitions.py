"""The strength definitions the verifier is given must be the constitution's.

The constitution is what authors read to learn how their arguments are judged,
and the verifier works from a copy in Python. Drift is silent: edit the
published wording and the agent goes on labelling by the old one.
"""
import re
from pathlib import Path

from app.core.checks_verification import STRENGTH_DEFINITIONS
from app.models.platform import ArgumentPosition, ArgumentStrength

CONSTITUTION = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "CONSTITUTION.md"
)


def _published_definitions() -> dict[ArgumentPosition, dict[ArgumentStrength, str]]:
    text = CONSTITUTION.read_text()
    section = re.search(r"^## Argument Strength$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert section, f"no '## Argument Strength' section found in {CONSTITUTION}"
    published = {}
    for position in ArgumentPosition:
        heading = f"### {position.value.capitalize()} arguments"
        block = re.search(rf"^{heading}$(.*?)(?=^### |\Z)", section.group(1), re.M | re.S)
        assert block, f"no '{heading}' subsection found under Argument Strength"
        items = re.findall(r"^- \*\*(\w+):\*\* (.*?)(?=^- |\Z)", block.group(1), re.M | re.S)
        assert items, f"no '- **Level:** definition' items found under '{heading}'"
        published[position] = {
            ArgumentStrength(level.lower()): " ".join(body.split()) for level, body in items
        }
    return published


def test_the_verifier_is_given_the_constitutions_definitions_word_for_word():
    assert STRENGTH_DEFINITIONS == _published_definitions()
