import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from icml_review_prompt import ICML_INSTRUCTIONS


def test_prompt_has_scales_and_review_only_directive():
    for anchor in ["Strong Accept", "Weak Reject", "confidence (1-5)",
                   "soundness / presentation / significance / originality (1-4)"]:
        assert anchor in ICML_INSTRUCTIONS
    assert "SOLELY on the paper" in ICML_INSTRUCTIONS


def test_prompt_has_no_acceptance_leakage():
    # The instructions must not assert this paper's outcome/venue.
    low = ICML_INSTRUCTIONS.lower()
    for leak in ["was accepted", "was rejected", "accepted at icml",
                 "this paper was", "decision:", "venue:"]:
        assert leak not in low
