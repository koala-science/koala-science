import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrape_openreview_conversations import (
    norm, surnames, parse_int, build_index, build_author_index, match_paper,
)

SUBS = [
    {"title": "Deep Widgets for Sparse Learning",
     "authors": ["Ada Lovelace", "Alan Turing"],
     "abstract": "We study deep widgets for sparse learning with gadgets and doohickeys."},
    {"title": "A Study of Gizmos",
     "authors": ["Grace Hopper", "Katherine Johnson"],
     "abstract": "We analyze gizmos in detail across many experimental settings."},
]


def _idx():
    title_index = build_index(SUBS)
    return title_index, list(title_index.keys()), build_author_index(SUBS)


def _match(title, abstract, authors):
    ti, titles, ai = _idx()
    return match_paper(title, abstract, authors, ti, titles, ai)


def test_norm_strips_punctuation_and_case():
    assert norm("Deep Widgets: For Sparse-Learning!") == "deep widgets for sparse learning"


def test_surnames_lastname_tokens():
    assert surnames(["Ada Lovelace", "Alan Turing"]) == {"lovelace", "turing"}


def test_parse_int_leading():
    assert parse_int("4") == 4
    assert parse_int("2: weak reject") == 2
    assert parse_int(None) is None


def test_exact_match():
    m = _match("deep widgets for sparse learning", "", ["Someone Else"])
    assert m["method"] == "exact"
    assert m["submission"]["title"] == "Deep Widgets for Sparse Learning"


def test_fuzzy_match_confirmed_by_author():
    m = _match("Deep Widgets for Sparse Learning (v2)", "", ["A. Lovelace", "Ada Lovelace"])
    assert m["method"] == "fuzzy"
    assert m["submission"]["title"] == "Deep Widgets for Sparse Learning"
    assert m["score"] >= 90.0


def test_fuzzy_rejected_when_authors_disjoint():
    m = _match("Deep Widgets for Sparse Learning extended", "", ["Totally Different"])
    assert m["method"] == "none"
    assert m["submission"] is None


def test_no_match_low_similarity():
    m = _match("An Unrelated Paper About Turtles", "", ["Ada Lovelace"])
    assert m["method"] == "none"


def test_author_abstract_fallback_recovers_rename():
    # Title shares nothing with any submission, but full author set + abstract match.
    m = _match("Autoformulation of Clinical Scoring Systems", SUBS[0]["abstract"],
               ["Ada Lovelace", "Alan Turing"])
    assert m["method"] == "author_abstract"
    assert m["submission"]["title"] == "Deep Widgets for Sparse Learning"


def test_author_abstract_fallback_rejected_when_abstract_differs():
    # Same authors, but abstract is unrelated -> prolific-author false positive, reject.
    m = _match("Some Other Paper", "This work is entirely about turtles in the ocean.",
               ["Ada Lovelace", "Alan Turing"])
    assert m["method"] == "none"


def test_author_abstract_fallback_needs_two_authors():
    # Single shared author must not trigger the fallback (no full-set key).
    m = _match("Unrelated Title", SUBS[1]["abstract"], ["Grace Hopper"])
    assert m["method"] == "none"
