import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_review_icml import out_path


def test_out_path_is_model_specific():
    assert out_path("claude-haiku-4-5").name == "icml_2026_claude_icml_reviews_claude-haiku-4-5.jsonl"
    assert out_path("claude-sonnet-5").name == "icml_2026_claude_icml_reviews_claude-sonnet-5.jsonl"
    assert out_path("claude-haiku-4-5") != out_path("claude-sonnet-5")
