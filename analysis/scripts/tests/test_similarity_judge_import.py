"""The analysis side can load the judge that now lives in the backend.

The stakes are the checkpoint files. ``data/coverage_*_judge_progress.jsonl``
holds thousands of already-paid-for four-way labels, and ``coverage_pipeline.py``
resumes from them. If the shared mapping stopped recognising those labels, a
resumed run would quietly re-judge work that was already bought.

The label semantics themselves are covered in
``backend/tests/test_similarity_judge.py``; what this file adds is that the
import works from the analysis venv, which has no database and no settings.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from app.core.similarity_judge import SYSTEM_PROMPT, is_duplicate  # noqa: E402

LEGACY_LABELS = [
    "same subject, same argument, same evidence",
    "same subject, same argument, different evidence",
    "same subject, different argument",
    "different subject",
]


def test_imports_without_a_configured_backend():
    assert SYSTEM_PROMPT


def test_every_legacy_checkpoint_label_still_resolves():
    assert [is_duplicate(label) for label in LEGACY_LABELS] == [True, True, False, False]
