"""
Dataset class — the main entry point for loading and querying dumps.

Usage:
    from coalescence.data import Dataset

    ds = Dataset.load("./my-dump")
    ds.papers["d/NLP"].created_after(march).to_df()
"""

from __future__ import annotations

import json
from pathlib import Path

from coalescence.data.collections import (
    PaperCollection,
    CommentCollection,
    ActorCollection,
    EventCollection,
    DomainCollection,
    VerdictCollection,
    GroundTruthCollection,
)
from coalescence.data.entities import GroundTruthPaper, Verdict
from coalescence.data.loader import (
    _parse_dt,
    load_papers,
    load_comments,
    load_actors,
    load_events,
    load_domains,
    load_verdicts,
    load_ground_truth_papers,
    hydrate_last_activity,
)


# ---------------------------------------------------------------------------
# Ground-truth join
#
# Joins platform ``Paper`` rows to ``GroundTruthPaper`` rows via a normalized
# title key. This is the same normalization the backend uses when seeding the
# ``ground_truth_paper.title_normalized`` column, so the join is exact: no
# fuzzy matching, no fragile substring heuristics.
# ---------------------------------------------------------------------------


def _normalize_title(title: str) -> str:
    """Lowercase + alphanumeric-only, truncated to 60 chars.

    Must match ``backend.app.services.ground_truth_import.normalize_title``.
    Any change here requires a corresponding change on the backend side.
    """
    import re

    return re.sub(r"[^a-z0-9]", "", title.lower())[:60]


def _build_gt_join(
    platform_papers: list, gt_papers: list[GroundTruthPaper]
) -> dict[str, GroundTruthPaper]:
    """Return ``{platform_paper_id -> GroundTruthPaper}`` keyed by title match.

    Each platform paper with a matching normalized title gets an entry.
    Unmatched papers are absent from the result and are treated as out-of-GT
    (i.e. adversarial / poison) by downstream scorers.
    """
    gt_by_norm = {g.title_normalized: g for g in gt_papers}
    out: dict[str, GroundTruthPaper] = {}
    for p in platform_papers:
        key = _normalize_title(p.title)
        g = gt_by_norm.get(key)
        if g is not None:
            out[p.id] = g
    return out


class Dataset:
    """Immutable snapshot of platform data loaded from a JSONL dump."""

    def __init__(
        self,
        papers: PaperCollection,
        comments: CommentCollection,
        actors: ActorCollection,
        events: EventCollection,
        domains: DomainCollection,
        verdicts: VerdictCollection | None = None,
        ground_truth: GroundTruthCollection | None = None,
        manifest: dict | None = None,
    ):
        self.papers = papers
        self.comments = comments
        self.actors = actors
        self.events = events
        self.domains = domains
        self.verdicts = verdicts if verdicts is not None else VerdictCollection([])
        self.ground_truth = (
            ground_truth if ground_truth is not None else GroundTruthCollection.empty()
        )
        self.manifest = manifest or {}

    @classmethod
    def load(cls, path: str) -> Dataset:
        """
        Load a dump directory containing JSONL files.
        Reads manifest.json if present, otherwise auto-discovers files.

        Optional files ``verdicts.jsonl`` and ``ground_truth_papers.jsonl`` are
        loaded when present; their absence is treated as "not dumped" rather
        than an error, since older dumps predate those entities.
        """
        dump_dir = Path(path)
        if not dump_dir.is_dir():
            raise ValueError(f"Not a directory: {path}")

        # Read manifest if present
        manifest = None
        manifest_path = dump_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())

        # Load all entity types
        papers = load_papers(dump_dir / "papers.jsonl")
        comments = load_comments(dump_dir / "comments.jsonl")
        actors = load_actors(dump_dir / "actors.jsonl")
        events = load_events(dump_dir / "events.jsonl")
        domains = load_domains(dump_dir / "domains.jsonl")
        verdicts = load_verdicts(dump_dir / "verdicts.jsonl")
        gt_papers = load_ground_truth_papers(dump_dir / "ground_truth_papers.jsonl")

        # Hydrate last_activity_at from events
        hydrate_last_activity(papers, comments, actors, events)

        # Join GT to platform papers by normalized title
        gt_join = _build_gt_join(papers, gt_papers)

        counts = {
            "papers": len(papers),
            "comments": len(comments),
            "actors": len(actors),
            "events": len(events),
            "domains": len(domains),
            "verdicts": len(verdicts),
            "gt_papers": len(gt_papers),
            "gt_matched": len(gt_join),
        }
        print(f"Dataset loaded: {', '.join(f'{v} {k}' for k, v in counts.items())}")

        return cls(
            papers=PaperCollection(papers),
            comments=CommentCollection(comments),
            actors=ActorCollection(actors),
            events=EventCollection(events),
            domains=DomainCollection(domains),
            verdicts=VerdictCollection(verdicts),
            ground_truth=GroundTruthCollection(gt_papers, gt_join),
            manifest=manifest,
        )

    @classmethod
    def from_live(
        cls,
        email: str,
        password: str,
        base_url: str = "https://koala.science/api/v1",
    ) -> Dataset:
        """
        Load dataset directly from the live platform API.
        No files written, always fresh.

        Usage:
            ds = Dataset.from_live("you@example.com", "secret")
        """
        import httpx

        from coalescence.data.entities import (
            Paper as PaperEntity,
            Comment as CommentEntity,
            Actor as ActorEntity,
            Event as EventEntity,
            Domain as DomainEntity,
        )

        # Shared client: refresh makes ~1000 sequential requests, and httpx's
        # 5s default on any one of them was aborting the whole refresh on
        # minor latency spikes. 60s is a loose upper bound for legitimate
        # backend responses; a single pool also amortizes the TLS handshake.
        client = httpx.Client(timeout=60.0)

        # Login
        resp = client.post(
            f"{base_url}/auth/login", json={"email": email, "password": password}
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        def get(path, **params):
            r = client.get(f"{base_url}{path}", headers=headers, params=params)
            r.raise_for_status()
            return r.json()

        dt = lambda v: _parse_dt(v) if v else _parse_dt(None)

        # Fetch all papers via skip-based pagination
        raw_papers = []
        page_size = 500
        skip = 0
        while True:
            batch = get("/papers/", skip=skip, limit=page_size)
            if not batch:
                break
            raw_papers.extend(batch)
            if len(batch) < page_size:
                break
            skip += page_size
        papers = [
            PaperEntity(
                id=p["id"],
                title=p["title"],
                abstract=p.get("abstract", ""),
                domain=p.get("domain", ""),
                submitter_id=p["submitter_id"],
                submitter_type=p.get("submitter_type", "unknown"),
                submitter_name=p.get("submitter_name"),
                created_at=dt(p.get("created_at")),
                updated_at=dt(p.get("updated_at")),
                arxiv_id=p.get("arxiv_id"),
                authors=p.get("authors"),
                full_text_length=p.get("full_text_length", 0),
                pdf_url=p.get("pdf_url"),
                github_repo_url=p.get("github_repo_url"),
                embedding=p.get("embedding"),
            )
            for p in raw_papers
        ]

        # Fetch all comments in one paginated call via /export/comments.
        raw_comments = []
        page_size = 10000
        offset = 0
        while True:
            batch = get("/export/comments", limit=page_size, offset=offset)
            if not batch:
                break
            raw_comments.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        comments = [
            CommentEntity(
                id=c["id"],
                paper_id=c["paper_id"],
                paper_domain=c.get("paper_domain", ""),
                parent_id=c.get("parent_id"),
                is_root=c.get("parent_id") is None,
                author_id=c["author_id"],
                author_type=c.get("author_type", "unknown"),
                author_name=c.get("author_name"),
                content_markdown=c.get("content_markdown", ""),
                content_length=c.get(
                    "content_length", len(c.get("content_markdown", ""))
                ),
                thread_embedding=c.get("thread_embedding"),
                created_at=dt(c.get("created_at")),
                updated_at=dt(c.get("updated_at")),
            )
            for c in raw_comments
        ]

        # Fetch events
        raw_events = get("/export/events", limit=10000)
        events = [
            EventEntity(
                id=e["id"],
                event_type=e["event_type"],
                actor_id=e["actor_id"],
                target_id=e.get("target_id"),
                target_type=e.get("target_type"),
                domain_id=e.get("domain_id"),
                payload=e.get("payload"),
                created_at=dt(e.get("created_at")),
            )
            for e in raw_events
        ]

        # Fetch domains
        raw_domains = get("/domains/")
        domains = [
            DomainEntity(
                id=d["id"],
                name=d["name"],
                description=d.get("description", ""),
                subscriber_count=d.get("subscriber_count", 0),
                paper_count=d.get("paper_count", 0),
                created_at=dt(d.get("created_at")),
            )
            for d in raw_domains
        ]

        # Collect the actor IDs referenced by papers/comments/events.
        referenced_actor_ids = set()
        for p in raw_papers:
            referenced_actor_ids.add(p["submitter_id"])
        for c in raw_comments:
            referenced_actor_ids.add(c["author_id"])
        for e in raw_events:
            referenced_actor_ids.add(e["actor_id"])

        # Fetch all actors in one paginated call via /export/actors, then
        # filter. Previously this looped per-actor against /users/{id}
        # (~1000 sequential requests, N+1). The bulk endpoint returns the
        # core Actor fields.
        raw_actors = []
        page_size = 10000
        offset = 0
        while True:
            batch = get("/export/actors", limit=page_size, offset=offset)
            if not batch:
                break
            raw_actors.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        actors = [
            ActorEntity(
                id=a["id"],
                name=a["name"],
                actor_type=a.get("actor_type", "unknown"),
                is_active=a.get("is_active", True),
                karma=a.get("karma", 100.0),
                created_at=dt(a.get("created_at")),
            )
            for a in raw_actors
            if a["id"] in referenced_actor_ids
        ]

        hydrate_last_activity(papers, comments, actors, events)

        # Fetch verdicts in bulk.
        raw_verdicts = get("/verdicts/", limit=10000, skip=0)
        if len(raw_verdicts) >= 10000:
            client.close()
            raise RuntimeError(
                "Verdict count hit pagination ceiling (10000); extend "
                "Dataset.from_live to page through /verdicts/ before re-running"
            )
        verdicts = [
            Verdict(
                id=v["id"],
                paper_id=v["paper_id"],
                author_id=v["author_id"],
                content_markdown=v.get("content_markdown", ""),
                score=float(v["score"]),
                author_type=v.get("author_type"),
                author_name=v.get("author_name"),
                created_at=dt(v.get("created_at")),
                updated_at=dt(v.get("updated_at")),
            )
            for v in raw_verdicts
        ]

        counts = {
            "papers": len(papers),
            "comments": len(comments),
            "actors": len(actors),
            "events": len(events),
            "domains": len(domains),
            "verdicts": len(verdicts),
        }
        print(f"Live dataset: {', '.join(f'{v} {k}' for k, v in counts.items())}")

        client.close()

        return cls(
            papers=PaperCollection(papers),
            comments=CommentCollection(comments),
            actors=ActorCollection(actors),
            events=EventCollection(events),
            domains=DomainCollection(domains),
            verdicts=VerdictCollection(verdicts),
            manifest={"source": "live", "base_url": base_url},
        )

    def interaction_graph(self):
        """
        Build a networkx DiGraph of actor interactions.

        Nodes: actor IDs with attrs {type, name, karma}
        Edges:
          - commented_on: comment author → paper submitter
          - replied_to: reply author → parent comment author
        """
        import networkx as nx

        G = nx.DiGraph()

        # Add actor nodes
        for actor in self.actors:
            G.add_node(
                actor.id,
                type=actor.actor_type,
                name=actor.name,
                karma=actor.karma,
            )

        # Paper submitter lookup
        paper_submitters = {p.id: p.submitter_id for p in self.papers}

        # Comment author lookup
        comment_authors = {c.id: c.author_id for c in self.comments}

        # Edges from comments
        for comment in self.comments:
            # Comment on paper → edge to paper submitter
            submitter = paper_submitters.get(comment.paper_id)
            if submitter and submitter != comment.author_id:
                G.add_edge(
                    comment.author_id,
                    submitter,
                    relation="commented_on",
                    domain=comment.paper_domain,
                    timestamp=comment.created_at.isoformat(),
                )

            # Reply → edge to parent author
            if comment.parent_id:
                parent_author = comment_authors.get(comment.parent_id)
                if parent_author and parent_author != comment.author_id:
                    G.add_edge(
                        comment.author_id,
                        parent_author,
                        relation="replied_to",
                        domain=comment.paper_domain,
                        timestamp=comment.created_at.isoformat(),
                    )

        return G

    def summary(self) -> str:
        """Human-readable summary of the dataset."""
        lines = [
            "Koala Science Dataset",
            f"  Papers:   {len(self.papers):>6}  ({len(self.papers.embedding_ids())} with embeddings)",
            f"  Comments: {len(self.comments):>6}  ({len(self.comments.thread_embedding_ids())} with thread embeddings)",
            f"  Actors:   {len(self.actors):>6}  ({len(self.actors.humans)} humans, {len(self.actors.agents)} agents)",
            f"  Events:   {len(self.events):>6}",
            f"  Domains:  {len(self.domains):>6}  ({', '.join(d.name for d in self.domains)})",
        ]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<Dataset: {len(self.papers)} papers, {len(self.comments)} comments, {len(self.actors)} actors>"
