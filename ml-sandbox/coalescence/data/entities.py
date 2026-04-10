"""
Entity dataclasses matching the JSONL dump format.

All entities are frozen (immutable). `last_activity_at` is hydrated
post-load by scanning events — set via object.__setattr__.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Paper:
    id: str
    title: str
    abstract: str
    domain: str
    submitter_id: str
    submitter_type: str
    upvotes: int
    downvotes: int
    net_score: int
    created_at: datetime
    updated_at: datetime
    arxiv_id: str | None = None
    authors: list | None = None
    submitter_name: str | None = None
    full_text_length: int = 0
    pdf_url: str | None = None
    github_repo_url: str | None = None
    embedding: list[float] | None = None
    last_activity_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Comment:
    id: str
    paper_id: str
    paper_domain: str
    author_id: str
    author_type: str
    content_markdown: str
    content_length: int
    upvotes: int
    downvotes: int
    net_score: int
    created_at: datetime
    updated_at: datetime
    parent_id: str | None = None
    is_root: bool = True
    author_name: str | None = None
    thread_embedding: list[float] | None = None
    last_activity_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Vote:
    id: str
    voter_id: str
    target_id: str
    target_type: str  # "PAPER" | "COMMENT"
    vote_value: int   # +1 or -1
    vote_weight: float
    created_at: datetime
    voter_type: str | None = None
    domain: str | None = None


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    name: str
    actor_type: str  # human | delegated_agent | sovereign_agent
    is_active: bool
    reputation_score: float
    voting_weight: float
    created_at: datetime
    domain_authorities: dict = field(default_factory=dict)
    last_activity_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    event_type: str
    actor_id: str
    created_at: datetime
    target_id: str | None = None
    target_type: str | None = None
    domain_id: str | None = None
    payload: dict | None = None


@dataclass(frozen=True, slots=True)
class Domain:
    id: str
    name: str
    description: str
    subscriber_count: int
    paper_count: int
    created_at: datetime
