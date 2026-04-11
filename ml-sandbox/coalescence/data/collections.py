"""
Indexed collection wrappers with chainable filters.

All filter methods return new collection instances. Collections are
lightweight — they share the underlying entity references.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TypeVar, Generic, Iterator

import numpy as np
import pandas as pd

from coalescence.data.entities import (
    Paper,
    Comment,
    Vote,
    Actor,
    Event,
    Domain,
    Verdict,
    GroundTruthPaper,
)

T = TypeVar("T")


# --- Base Collection ---


class BaseCollection(Generic[T]):
    """Base with shared filter and export methods."""

    def __init__(self, items: list[T]):
        self._items = items

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return len(self._items) > 0

    def to_list(self) -> list[T]:
        return list(self._items)

    def to_df(self) -> pd.DataFrame:
        if not self._items:
            return pd.DataFrame()
        from dataclasses import asdict

        return pd.DataFrame([asdict(item) for item in self._items])

    def _filter(self, predicate) -> list[T]:
        return [item for item in self._items if predicate(item)]

    def created_after(self, dt: datetime):
        return self.__class__(self._filter(lambda x: x.created_at >= dt))

    def created_before(self, dt: datetime):
        return self.__class__(self._filter(lambda x: x.created_at < dt))

    def last_activity_after(self, dt: datetime):
        return self.__class__(
            self._filter(
                lambda x: (
                    getattr(x, "last_activity_at", None) is not None
                    and x.last_activity_at >= dt
                )
            )
        )

    def last_activity_before(self, dt: datetime):
        return self.__class__(
            self._filter(
                lambda x: (
                    getattr(x, "last_activity_at", None) is not None
                    and x.last_activity_at < dt
                )
            )
        )


# --- Paper Collection ---


class PaperCollection(BaseCollection[Paper]):
    def __init__(self, items: list[Paper]):
        super().__init__(items)
        self._by_id: dict[str, Paper] = {p.id: p for p in items}
        self._by_domain: dict[str, list[Paper]] = defaultdict(list)
        self._by_submitter: dict[str, list[Paper]] = defaultdict(list)
        for p in items:
            self._by_domain[p.domain].append(p)
            self._by_submitter[p.submitter_id].append(p)
        self._embedding_cache: np.ndarray | None = None

    def __getitem__(self, key: str) -> PaperCollection:
        """Filter by domain: ds.papers['d/NLP']"""
        if key in self._by_domain:
            return PaperCollection(self._by_domain[key])
        raise KeyError(f"Domain '{key}' not found")

    def get(self, paper_id: str) -> Paper | None:
        return self._by_id.get(paper_id)

    def by_author(self, actor_id: str) -> PaperCollection:
        return PaperCollection(self._by_submitter.get(actor_id, []))

    @property
    def domains(self) -> list[str]:
        return list(self._by_domain.keys())

    def embeddings(self) -> np.ndarray:
        """Return (n, 768) numpy array of paper embeddings. Lazy, cached."""
        if self._embedding_cache is not None:
            return self._embedding_cache
        vecs = [p.embedding for p in self._items if p.embedding]
        self._embedding_cache = (
            np.array(vecs, dtype=np.float32)
            if vecs
            else np.empty((0, 768), dtype=np.float32)
        )
        return self._embedding_cache

    def embedding_ids(self) -> list[str]:
        """Paper IDs corresponding to rows in embeddings()."""
        return [p.id for p in self._items if p.embedding]


# --- Comment Collection ---


class CommentCollection(BaseCollection[Comment]):
    def __init__(self, items: list[Comment]):
        super().__init__(items)
        self._by_id: dict[str, Comment] = {c.id: c for c in items}
        self._by_paper: dict[str, list[Comment]] = defaultdict(list)
        self._by_author: dict[str, list[Comment]] = defaultdict(list)
        self._by_parent: dict[str, list[Comment]] = defaultdict(list)
        self._roots_by_paper: dict[str, list[Comment]] = defaultdict(list)
        for c in items:
            self._by_paper[c.paper_id].append(c)
            self._by_author[c.author_id].append(c)
            if c.parent_id:
                self._by_parent[c.parent_id].append(c)
            if c.is_root:
                self._roots_by_paper[c.paper_id].append(c)
        self._embedding_cache: np.ndarray | None = None

    def get(self, comment_id: str) -> Comment | None:
        return self._by_id.get(comment_id)

    def by_author(self, actor_id: str) -> CommentCollection:
        return CommentCollection(self._by_author.get(actor_id, []))

    def for_paper(self, paper_id: str) -> CommentCollection:
        return CommentCollection(self._by_paper.get(paper_id, []))

    def roots_for(self, paper_id: str) -> CommentCollection:
        return CommentCollection(self._roots_by_paper.get(paper_id, []))

    def children(self, comment_id: str) -> CommentCollection:
        """Direct replies to a comment."""
        return CommentCollection(self._by_parent.get(comment_id, []))

    def subtree(self, comment_id: str) -> CommentCollection:
        """Full reply chain depth-first from a comment."""
        result: list[Comment] = []

        def walk(cid: str):
            for child in self._by_parent.get(cid, []):
                result.append(child)
                walk(child.id)

        root = self._by_id.get(comment_id)
        if root:
            result.append(root)
        walk(comment_id)
        return CommentCollection(result)

    def thread_embeddings(self) -> np.ndarray:
        """Return (m, 768) numpy array of thread embeddings (root comments only). Lazy, cached."""
        if self._embedding_cache is not None:
            return self._embedding_cache
        vecs = [c.thread_embedding for c in self._items if c.thread_embedding]
        self._embedding_cache = (
            np.array(vecs, dtype=np.float32)
            if vecs
            else np.empty((0, 768), dtype=np.float32)
        )
        return self._embedding_cache

    def thread_embedding_ids(self) -> list[str]:
        """Comment IDs corresponding to rows in thread_embeddings()."""
        return [c.id for c in self._items if c.thread_embedding]


# --- Vote Collection ---


class VoteCollection(BaseCollection[Vote]):
    def __init__(self, items: list[Vote]):
        super().__init__(items)
        self._by_target: dict[str, list[Vote]] = defaultdict(list)
        self._by_voter: dict[str, list[Vote]] = defaultdict(list)
        for v in items:
            self._by_target[v.target_id].append(v)
            self._by_voter[v.voter_id].append(v)

    def for_target(self, target_id: str) -> VoteCollection:
        return VoteCollection(self._by_target.get(target_id, []))

    def by_voter(self, voter_id: str) -> VoteCollection:
        return VoteCollection(self._by_voter.get(voter_id, []))

    @property
    def upvotes(self) -> VoteCollection:
        return VoteCollection([v for v in self._items if v.vote_value > 0])

    @property
    def downvotes(self) -> VoteCollection:
        return VoteCollection([v for v in self._items if v.vote_value < 0])


# --- Actor Collection ---


class ActorCollection(BaseCollection[Actor]):
    def __init__(self, items: list[Actor]):
        super().__init__(items)
        self._by_id: dict[str, Actor] = {a.id: a for a in items}

    def get(self, actor_id: str) -> Actor | None:
        return self._by_id.get(actor_id)

    @property
    def humans(self) -> ActorCollection:
        return ActorCollection([a for a in self._items if a.actor_type == "human"])

    @property
    def agents(self) -> ActorCollection:
        return ActorCollection([a for a in self._items if a.actor_type != "human"])


# --- Event Collection ---


class EventCollection(BaseCollection[Event]):
    def __init__(self, items: list[Event]):
        super().__init__(items)
        self._by_type: dict[str, list[Event]] = defaultdict(list)
        self._by_actor: dict[str, list[Event]] = defaultdict(list)
        for e in items:
            self._by_type[e.event_type].append(e)
            self._by_actor[e.actor_id].append(e)

    def of_type(self, event_type: str) -> EventCollection:
        return EventCollection(self._by_type.get(event_type, []))

    def by_actor(self, actor_id: str) -> EventCollection:
        return EventCollection(self._by_actor.get(actor_id, []))


# --- Domain Collection ---


class DomainCollection(BaseCollection[Domain]):
    def __init__(self, items: list[Domain]):
        super().__init__(items)
        self._by_id: dict[str, Domain] = {d.id: d for d in items}
        self._by_name: dict[str, Domain] = {d.name: d for d in items}

    def get(self, key: str) -> Domain | None:
        return self._by_name.get(key) or self._by_id.get(key)


# --- Verdict Collection ---


class VerdictCollection(BaseCollection[Verdict]):
    """Verdicts indexed by (paper, author) and by author for fast lookups.

    Enforces the model-level ``(author_id, paper_id)`` uniqueness: duplicate
    rows in the input are rejected rather than silently deduplicated, so the
    loader surfaces data integrity problems immediately.
    """

    def __init__(self, items: list[Verdict]):
        super().__init__(items)
        self._by_id: dict[str, Verdict] = {}
        self._by_paper: dict[str, list[Verdict]] = defaultdict(list)
        self._by_author: dict[str, list[Verdict]] = defaultdict(list)
        self._by_author_paper: dict[tuple[str, str], Verdict] = {}
        for v in items:
            self._by_id[v.id] = v
            self._by_paper[v.paper_id].append(v)
            self._by_author[v.author_id].append(v)
            key = (v.author_id, v.paper_id)
            if key in self._by_author_paper:
                raise ValueError(
                    f"Duplicate verdict for author={v.author_id} paper={v.paper_id}; "
                    "verdicts must be unique per (author, paper) per the backend model"
                )
            self._by_author_paper[key] = v

    def get(self, verdict_id: str) -> Verdict | None:
        return self._by_id.get(verdict_id)

    def by_author(self, author_id: str) -> VerdictCollection:
        return VerdictCollection(self._by_author.get(author_id, []))

    def for_paper(self, paper_id: str) -> VerdictCollection:
        return VerdictCollection(self._by_paper.get(paper_id, []))

    def for_author_paper(self, author_id: str, paper_id: str) -> Verdict | None:
        return self._by_author_paper.get((author_id, paper_id))

    @property
    def authors(self) -> set[str]:
        """All distinct agent IDs that have posted at least one verdict."""
        return set(self._by_author.keys())


# --- Ground-truth Collection ---


class GroundTruthCollection:
    """Keyed lookup over ``GroundTruthPaper`` rows joined to platform papers.

    This collection is built post-load by joining on ``title_normalized`` so
    downstream scorers can resolve platform ``paper_id -> GroundTruthPaper``
    in O(1). Platform papers without a matching GT row are absent from the
    index (a ``None`` return from ``get``) — callers treat those as
    adversarial / poison for correlation purposes.
    """

    def __init__(
        self,
        gt_papers: list[GroundTruthPaper],
        platform_paper_to_gt: dict[str, GroundTruthPaper],
    ):
        self._gt_papers = gt_papers
        self._by_platform_id = platform_paper_to_gt
        self._by_openreview_id: dict[str, GroundTruthPaper] = {
            g.openreview_id: g for g in gt_papers
        }

    def __iter__(self) -> Iterator[GroundTruthPaper]:
        return iter(self._gt_papers)

    def __len__(self) -> int:
        return len(self._gt_papers)

    def __bool__(self) -> bool:
        return len(self._gt_papers) > 0

    def get(self, platform_paper_id: str) -> GroundTruthPaper | None:
        """Lookup GT by platform paper UUID. Returns None if unmatched."""
        return self._by_platform_id.get(platform_paper_id)

    def by_openreview_id(self, openreview_id: str) -> GroundTruthPaper | None:
        return self._by_openreview_id.get(openreview_id)

    @property
    def matched_platform_paper_ids(self) -> set[str]:
        """Set of platform paper IDs that have a GT match (i.e. are scorable)."""
        return set(self._by_platform_id.keys())

    def is_matched(self, platform_paper_id: str) -> bool:
        return platform_paper_id in self._by_platform_id

    @classmethod
    def empty(cls) -> GroundTruthCollection:
        return cls([], {})
