"""
JSONL parsing and manifest reading.

Loads dump files into entity dataclasses, then hydrates last_activity_at
by scanning events.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from coalescence.data.entities import Paper, Comment, Vote, Actor, Event, Domain


def _parse_dt(val) -> datetime:
    """Parse a datetime from ISO string or return epoch if missing."""
    if val is None:
        return datetime(1970, 1, 1)
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(str(val).replace("Z", "+00:00").replace("+00:00", ""))


def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file into a list of dicts."""
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_papers(path: Path) -> list[Paper]:
    return [
        Paper(
            id=r["id"],
            title=r["title"],
            abstract=r["abstract"],
            domain=r["domain"],
            submitter_id=r["submitter_id"],
            submitter_type=r.get("submitter_type", "unknown"),
            submitter_name=r.get("submitter_name"),
            upvotes=r.get("upvotes", 0),
            downvotes=r.get("downvotes", 0),
            net_score=r.get("net_score", 0),
            created_at=_parse_dt(r.get("created_at")),
            updated_at=_parse_dt(r.get("updated_at")),
            arxiv_id=r.get("arxiv_id"),
            authors=r.get("authors"),
            full_text_length=r.get("full_text_length", 0),
            pdf_url=r.get("pdf_url"),
            github_repo_url=r.get("github_repo_url"),
            embedding=r.get("embedding"),
        )
        for r in _load_jsonl(path)
    ]


def load_comments(path: Path) -> list[Comment]:
    return [
        Comment(
            id=r["id"],
            paper_id=r["paper_id"],
            paper_domain=r.get("paper_domain", ""),
            parent_id=r.get("parent_id"),
            is_root=r.get("is_root", r.get("parent_id") is None),
            author_id=r["author_id"],
            author_type=r.get("author_type", "unknown"),
            author_name=r.get("author_name"),
            content_markdown=r.get("content_markdown", ""),
            content_length=r.get("content_length", len(r.get("content_markdown", ""))),
            upvotes=r.get("upvotes", 0),
            downvotes=r.get("downvotes", 0),
            net_score=r.get("net_score", 0),
            thread_embedding=r.get("thread_embedding"),
            created_at=_parse_dt(r.get("created_at")),
            updated_at=_parse_dt(r.get("updated_at")),
        )
        for r in _load_jsonl(path)
    ]


def load_votes(path: Path) -> list[Vote]:
    return [
        Vote(
            id=r["id"],
            voter_id=r["voter_id"],
            voter_type=r.get("voter_type"),
            target_id=r["target_id"],
            target_type=r["target_type"],
            vote_value=r["vote_value"],
            vote_weight=r.get("vote_weight", 1.0),
            domain=r.get("domain"),
            created_at=_parse_dt(r.get("created_at")),
        )
        for r in _load_jsonl(path)
    ]


def load_actors(path: Path) -> list[Actor]:
    return [
        Actor(
            id=r["id"],
            name=r["name"],
            actor_type=r["actor_type"],
            is_active=r.get("is_active", True),
            reputation_score=r.get("reputation_score", 0),
            voting_weight=r.get("voting_weight", 1.0),
            domain_authorities=r.get("domain_authorities", {}),
            created_at=_parse_dt(r.get("created_at")),
        )
        for r in _load_jsonl(path)
    ]


def load_events(path: Path) -> list[Event]:
    return [
        Event(
            id=r["id"],
            event_type=r["event_type"],
            actor_id=r["actor_id"],
            target_id=r.get("target_id"),
            target_type=r.get("target_type"),
            domain_id=r.get("domain_id"),
            payload=r.get("payload"),
            created_at=_parse_dt(r.get("created_at")),
        )
        for r in _load_jsonl(path)
    ]


def load_domains(path: Path) -> list[Domain]:
    return [
        Domain(
            id=r["id"],
            name=r["name"],
            description=r.get("description", ""),
            subscriber_count=r.get("subscriber_count", 0),
            paper_count=r.get("paper_count", 0),
            created_at=_parse_dt(r.get("created_at")),
        )
        for r in _load_jsonl(path)
    ]


def hydrate_last_activity(
    papers: list[Paper],
    comments: list[Comment],
    actors: list[Actor],
    events: list[Event],
) -> None:
    """
    Compute and set last_activity_at on papers, comments, and actors
    by scanning events. Mutates frozen dataclasses via object.__setattr__.
    """
    # Build lookup: entity_id → max event created_at
    paper_activity: dict[str, datetime] = {}
    comment_activity: dict[str, datetime] = {}
    actor_activity: dict[str, datetime] = {}

    # Also track comment replies for comment last_activity
    comment_by_parent: dict[str, list[Comment]] = {}
    for c in comments:
        if c.parent_id:
            comment_by_parent.setdefault(c.parent_id, []).append(c)

    for event in events:
        dt = event.created_at

        # Actor activity
        if event.actor_id:
            if event.actor_id not in actor_activity or dt > actor_activity[event.actor_id]:
                actor_activity[event.actor_id] = dt

        # Paper activity: events targeting paper or with paper_id in payload
        if event.target_id and event.target_type == "PAPER":
            if event.target_id not in paper_activity or dt > paper_activity[event.target_id]:
                paper_activity[event.target_id] = dt

        payload = event.payload or {}
        paper_id = payload.get("paper_id")
        if paper_id:
            if paper_id not in paper_activity or dt > paper_activity[paper_id]:
                paper_activity[paper_id] = dt

        # Comment activity: votes on comments
        if event.target_id and event.target_type == "COMMENT":
            if event.target_id not in comment_activity or dt > comment_activity[event.target_id]:
                comment_activity[event.target_id] = dt

    # Comment activity from replies
    for parent_id, replies in comment_by_parent.items():
        latest_reply = max(r.created_at for r in replies)
        if parent_id not in comment_activity or latest_reply > comment_activity[parent_id]:
            comment_activity[parent_id] = latest_reply

    # Apply to entities
    for p in papers:
        if p.id in paper_activity:
            object.__setattr__(p, "last_activity_at", paper_activity[p.id])

    for c in comments:
        if c.id in comment_activity:
            object.__setattr__(c, "last_activity_at", comment_activity[c.id])

    for a in actors:
        if a.id in actor_activity:
            object.__setattr__(a, "last_activity_at", actor_activity[a.id])
