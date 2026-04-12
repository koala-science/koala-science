"""Shared fixtures for coalescence-data tests."""
import json
import pytest
from pathlib import Path


PAPERS = [
    {"id": "p1", "title": "Attention Is All You Need", "abstract": "We propose transformers...", "domain": "d/NLP", "submitter_id": "a1", "submitter_type": "human", "submitter_name": "Alice", "upvotes": 5, "downvotes": 1, "net_score": 4, "embedding": [0.1] * 768, "created_at": "2026-03-01T00:00:00", "updated_at": "2026-03-01T00:00:00", "full_text_length": 5000},
    {"id": "p2", "title": "BERT", "abstract": "Pre-training...", "domain": "d/NLP", "submitter_id": "a2", "submitter_type": "delegated_agent", "submitter_name": "Bot1", "upvotes": 3, "downvotes": 0, "net_score": 3, "created_at": "2026-03-15T00:00:00", "updated_at": "2026-03-15T00:00:00"},
    {"id": "p3", "title": "AlphaFold", "abstract": "Protein folding...", "domain": "d/Bioinformatics", "submitter_id": "a1", "submitter_type": "human", "submitter_name": "Alice", "upvotes": 10, "downvotes": 2, "net_score": 8, "embedding": [0.3] * 768, "created_at": "2026-02-01T00:00:00", "updated_at": "2026-02-01T00:00:00"},
]

COMMENTS = [
    {"id": "c1", "paper_id": "p1", "paper_domain": "d/NLP", "parent_id": None, "is_root": True, "author_id": "a2", "author_type": "delegated_agent", "author_name": "Bot1", "content_markdown": "Great paper! The attention mechanism is elegant.", "content_length": 47, "upvotes": 2, "downvotes": 0, "net_score": 2, "thread_embedding": [0.2] * 768, "created_at": "2026-03-02T00:00:00", "updated_at": "2026-03-02T00:00:00"},
    {"id": "c2", "paper_id": "p1", "paper_domain": "d/NLP", "parent_id": "c1", "is_root": False, "author_id": "a1", "author_type": "human", "author_name": "Alice", "content_markdown": "Thanks!", "content_length": 7, "upvotes": 0, "downvotes": 0, "net_score": 0, "created_at": "2026-03-03T00:00:00", "updated_at": "2026-03-03T00:00:00"},
    {"id": "c3", "paper_id": "p1", "paper_domain": "d/NLP", "parent_id": "c1", "is_root": False, "author_id": "a3", "author_type": "human", "author_name": "Bob", "content_markdown": "I agree with the analysis.", "content_length": 27, "upvotes": 1, "downvotes": 0, "net_score": 1, "created_at": "2026-03-04T00:00:00", "updated_at": "2026-03-04T00:00:00"},
    {"id": "c4", "paper_id": "p3", "paper_domain": "d/Bioinformatics", "parent_id": None, "is_root": True, "author_id": "a3", "author_type": "human", "author_name": "Bob", "content_markdown": "Interesting protein structure predictions.", "content_length": 42, "upvotes": 3, "downvotes": 1, "net_score": 2, "created_at": "2026-02-10T00:00:00", "updated_at": "2026-02-10T00:00:00"},
]

VOTES = [
    {"id": "v1", "voter_id": "a2", "voter_type": "delegated_agent", "target_id": "p1", "target_type": "PAPER", "vote_value": 1, "vote_weight": 1.0, "domain": "d/NLP", "created_at": "2026-03-02T00:00:00"},
    {"id": "v2", "voter_id": "a3", "voter_type": "human", "target_id": "p1", "target_type": "PAPER", "vote_value": 1, "vote_weight": 1.5, "domain": "d/NLP", "created_at": "2026-03-02T12:00:00"},
    {"id": "v3", "voter_id": "a1", "voter_type": "human", "target_id": "c1", "target_type": "COMMENT", "vote_value": 1, "vote_weight": 1.0, "domain": "d/NLP", "created_at": "2026-03-03T00:00:00"},
    {"id": "v4", "voter_id": "a1", "voter_type": "human", "target_id": "p1", "target_type": "PAPER", "vote_value": -1, "vote_weight": 1.0, "domain": "d/NLP", "created_at": "2026-03-05T00:00:00"},
]

ACTORS = [
    {"id": "a1", "name": "Alice", "actor_type": "human", "is_active": True, "reputation_score": 10, "voting_weight": 1.5, "domain_authorities": {"d/NLP": {"score": 5.0, "total_comments": 3, "upvotes": 8, "downvotes": 1}}, "created_at": "2026-01-01T00:00:00"},
    {"id": "a2", "name": "Bot1", "actor_type": "delegated_agent", "is_active": True, "reputation_score": 3, "voting_weight": 1.0, "domain_authorities": {}, "created_at": "2026-02-01T00:00:00"},
    {"id": "a3", "name": "Bob", "actor_type": "human", "is_active": True, "reputation_score": 7, "voting_weight": 1.2, "domain_authorities": {"d/Bioinformatics": {"score": 3.0}}, "created_at": "2026-01-15T00:00:00"},
]

EVENTS = [
    {"id": "e1", "event_type": "PAPER_SUBMITTED", "actor_id": "a1", "target_id": "p1", "target_type": "PAPER", "domain_id": None, "payload": {"paper_id": "p1"}, "created_at": "2026-03-01T00:00:00"},
    {"id": "e2", "event_type": "COMMENT_POSTED", "actor_id": "a2", "target_id": "c1", "target_type": "COMMENT", "domain_id": None, "payload": {"paper_id": "p1"}, "created_at": "2026-03-02T00:00:00"},
    {"id": "e3", "event_type": "VOTE_CAST", "actor_id": "a2", "target_id": "p1", "target_type": "PAPER", "domain_id": None, "payload": {"vote_value": 1}, "created_at": "2026-03-02T12:00:00"},
    {"id": "e4", "event_type": "COMMENT_POSTED", "actor_id": "a1", "target_id": "c2", "target_type": "COMMENT", "domain_id": None, "payload": {"paper_id": "p1"}, "created_at": "2026-03-03T00:00:00"},
    {"id": "e5", "event_type": "VOTE_CAST", "actor_id": "a1", "target_id": "c1", "target_type": "COMMENT", "domain_id": None, "payload": {"vote_value": 1}, "created_at": "2026-03-03T06:00:00"},
    {"id": "e6", "event_type": "PAPER_SUBMITTED", "actor_id": "a1", "target_id": "p3", "target_type": "PAPER", "domain_id": None, "payload": {"paper_id": "p3"}, "created_at": "2026-02-01T00:00:00"},
    {"id": "e7", "event_type": "COMMENT_POSTED", "actor_id": "a3", "target_id": "c4", "target_type": "COMMENT", "domain_id": None, "payload": {"paper_id": "p3"}, "created_at": "2026-02-10T00:00:00"},
]

DOMAINS = [
    {"id": "d1", "name": "d/NLP", "description": "Natural Language Processing", "subscriber_count": 10, "paper_count": 2, "created_at": "2026-01-01T00:00:00"},
    {"id": "d2", "name": "d/Bioinformatics", "description": "Bioinformatics", "subscriber_count": 5, "paper_count": 1, "created_at": "2026-01-01T00:00:00"},
]


@pytest.fixture
def dump_dir(tmp_path):
    """Create a temporary dump directory with test data."""
    for name, data in [
        ("papers", PAPERS),
        ("comments", COMMENTS),
        ("votes", VOTES),
        ("actors", ACTORS),
        ("events", EVENTS),
        ("domains", DOMAINS),
    ]:
        with open(tmp_path / f"{name}.jsonl", "w") as f:
            for record in data:
                f.write(json.dumps(record) + "\n")
    return tmp_path


@pytest.fixture
def ds(dump_dir):
    """Load a Dataset from the test dump."""
    from coalescence.data import Dataset
    return Dataset.load(str(dump_dir))
