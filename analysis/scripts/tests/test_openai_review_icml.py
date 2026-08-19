import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai_review_icml import out_path


def test_out_path_is_model_specific():
    assert out_path("gpt-5.4-mini").name == "icml_2026_openai_icml_reviews_gpt-5.4-mini.jsonl"
    assert out_path("gpt-4.1-nano").name == "icml_2026_openai_icml_reviews_gpt-4.1-nano.jsonl"
    assert out_path("gpt-5.4-mini") != out_path("gpt-4.1-nano")
