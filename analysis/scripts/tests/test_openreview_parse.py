import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrape_openreview_conversations import parse_conversation, parse_submission

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "forum_sample.json").read_text())


def test_parse_submission():
    s = parse_submission(FIXTURE)
    assert s["forum_id"] == "SUBabc123"
    assert s["title"] == "Deep Widgets for Sparse Learning"
    assert s["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert s["venue"] == "ICML 2026 spotlight"
    assert s["keywords"] == ["widgets", "sparsity"]


def test_conversation_review_counts_drops_edit_stub():
    conv = parse_conversation(FIXTURE)
    assert len(conv["reviews"]) == 2  # the 3rd Official_Review has no summary -> dropped


def test_review_scores_parsed():
    conv = parse_conversation(FIXTURE)
    r0 = next(r for r in conv["reviews"] if r["reviewer"] == "Reviewer_QSzA")
    assert r0["overall_recommendation_int"] == 4
    assert r0["confidence_int"] == 3
    assert r0["soundness_int"] == 3
    assert r0["summary"] == "A clear paper on widgets."
    r1 = next(r for r in conv["reviews"] if r["reviewer"] == "Reviewer_KHSw")
    assert r1["overall_recommendation"] == "2: weak reject"
    assert r1["overall_recommendation_int"] == 2


def test_conversation_buckets():
    conv = parse_conversation(FIXTURE)
    assert len(conv["rebuttals"]) == 1
    assert conv["rebuttals"][0]["rebuttal"] == "We added baselines."
    assert len(conv["comments"]) == 1
    assert len(conv["rebuttal_acks"]) == 1
    assert conv["decision"]["decision"] == "Accept (spotlight)"
    assert conv["meta_reviews"] == []
