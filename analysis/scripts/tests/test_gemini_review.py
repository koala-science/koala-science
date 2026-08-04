import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from gemini_review import (
    build_system_prompt, build_config, parse_review, ICML_INSTRUCTIONS,
)

VALID = json.dumps({
    "summary": "A paper about widgets.",
    "strengths_and_weaknesses": "Strong method, weak baselines.",
    "soundness": 3, "presentation": 2, "significance": 3, "originality": 2,
    "key_questions_for_authors": "How does it scale?",
    "limitations": "yes",
    "overall_recommendation": 4, "confidence": 3,
})


def test_system_prompt_has_scales_and_review_only_directive():
    p = build_system_prompt()
    for anchor in ["Strong Accept", "Weak Reject", "confidence (1-5)",
                   "soundness / presentation / significance / originality (1-4)"]:
        assert anchor in p
    assert "SOLELY on the paper" in p


def test_prompt_has_no_acceptance_leakage():
    # The instructions must not assert this paper's outcome/venue.
    low = ICML_INSTRUCTIONS.lower()
    for leak in ["was accepted", "was rejected", "accepted at icml",
                 "this paper was", "decision:", "venue:"]:
        assert leak not in low


def test_config_has_no_tools():
    config = build_config(0.0)
    assert not config.tools
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0.0


def test_parse_review_valid():
    r = parse_review(VALID)
    assert r["overall_recommendation"] == 4
    assert r["soundness"] == 3
    assert r["confidence"] == 3
    assert isinstance(r["overall_recommendation"], int)
    assert r["summary"] == "A paper about widgets."


def test_parse_review_malformed_raises():
    with pytest.raises(Exception):
        parse_review('{"summary": "missing score fields"}')
