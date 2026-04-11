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
    VoteCollection,
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
    load_votes,
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
        votes: VoteCollection,
        actors: ActorCollection,
        events: EventCollection,
        domains: DomainCollection,
        verdicts: VerdictCollection | None = None,
        ground_truth: GroundTruthCollection | None = None,
        manifest: dict | None = None,
    ):
        self.papers = papers
        self.comments = comments
        self.votes = votes
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
        votes = load_votes(dump_dir / "votes.jsonl")
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
            "votes": len(votes),
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
            votes=VoteCollection(votes),
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
        base_url: str = "https://coale.science/api/v1",
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
            Vote as VoteEntity,
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
            batch = get("/papers/", skip=skip, limit=page_size, sort="new")
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
                upvotes=p.get("upvotes", 0),
                downvotes=p.get("downvotes", 0),
                net_score=p.get("net_score", 0),
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

        # Fetch comments per paper (skip papers with 0 comments)
        raw_comments = []
        for p in raw_papers:
            if p.get("comment_count", 0) > 0:
                raw_comments.extend(get(f"/comments/paper/{p['id']}", limit=500))
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
                upvotes=c.get("upvotes", 0),
                downvotes=c.get("downvotes", 0),
                net_score=c.get("net_score", 0),
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

        # Actors from unique IDs
        actor_ids = set()
        for p in raw_papers:
            actor_ids.add(p["submitter_id"])
        for c in raw_comments:
            actor_ids.add(c["author_id"])
        for e in raw_events:
            actor_ids.add(e["actor_id"])

        actors = []
        for aid in actor_ids:
            try:
                a = client.get(f"{base_url}/users/{aid}", headers=headers)
                if a.status_code == 200:
                    d = a.json()
                    actors.append(
                        ActorEntity(
                            id=d["id"],
                            name=d["name"],
                            actor_type=d.get("actor_type", "unknown"),
                            is_active=d.get("is_active", True),
                            reputation_score=d.get("reputation_score", 0),
                            voting_weight=d.get("voting_weight", 1.0),
                            domain_authorities=d.get("domain_authorities", {}),
                            created_at=dt(d.get("created_at")),
                        )
                    )
            except Exception:
                pass

        # Votes from events
        votes = [
            VoteEntity(
                id=e["id"],
                voter_id=e["actor_id"],
                voter_type=(e.get("payload") or {}).get("actor_type"),
                target_id=e.get("target_id"),
                target_type=e.get("target_type"),
                vote_value=(e.get("payload") or {}).get("vote_value", 0),
                vote_weight=(e.get("payload") or {}).get("vote_weight", 1.0),
                domain=(e.get("payload") or {}).get("domain"),
                created_at=dt(e.get("created_at")),
            )
            for e in raw_events
            if e["event_type"] == "VOTE_CAST"
        ]

        hydrate_last_activity(papers, comments, actors, events)

        # Fetch verdicts in bulk. Endpoint is paginated; a single call with a
        # generous page size is sufficient for the retreat's scale (<< 10k).
        # A future page-size overflow will manifest as a truncated list, which
        # we detect by comparing the returned count against the requested
        # page size and surfacing an error rather than silently losing rows.
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
                upvotes=v.get("upvotes", 0),
                downvotes=v.get("downvotes", 0),
                net_score=v.get("net_score", 0),
                author_type=v.get("author_type"),
                author_name=v.get("author_name"),
                created_at=dt(v.get("created_at")),
                updated_at=dt(v.get("updated_at")),
            )
            for v in raw_verdicts
        ]

        # Fetch ground-truth papers. Endpoint returns the full set keyed by
        # openreview_id with a title_normalized column that matches the
        # normalization we use for the join in ``_build_gt_join``.
        raw_gt = get("/leaderboard/ground-truth/")
        gt_papers = [
            GroundTruthPaper(
                openreview_id=g["openreview_id"],
                title_normalized=g["title_normalized"],
                decision=g["decision"],
                accepted=bool(g["accepted"]),
                year=int(g["year"]),
                avg_score=g.get("avg_score"),
                citations=g.get("citations"),
                primary_area=g.get("primary_area"),
            )
            for g in raw_gt
        ]

        gt_join = _build_gt_join(papers, gt_papers)

        counts = {
            "papers": len(papers),
            "comments": len(comments),
            "votes": len(votes),
            "actors": len(actors),
            "events": len(events),
            "domains": len(domains),
            "verdicts": len(verdicts),
            "gt_papers": len(gt_papers),
            "gt_matched": len(gt_join),
        }
        print(f"Live dataset: {', '.join(f'{v} {k}' for k, v in counts.items())}")

        client.close()

        return cls(
            papers=PaperCollection(papers),
            comments=CommentCollection(comments),
            votes=VoteCollection(votes),
            actors=ActorCollection(actors),
            events=EventCollection(events),
            domains=DomainCollection(domains),
            verdicts=VerdictCollection(verdicts),
            ground_truth=GroundTruthCollection(gt_papers, gt_join),
            manifest={"source": "live", "base_url": base_url},
        )

    def interaction_graph(self):
        """
        Build a networkx DiGraph of actor interactions.

        Nodes: actor IDs with attrs {type, name, reputation_score}
        Edges:
          - commented_on: comment author → paper submitter
          - voted_on: voter → comment/paper author
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
                reputation=actor.reputation_score,
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

        # Edges from votes
        for vote in self.votes:
            if vote.target_type == "PAPER":
                target_author = paper_submitters.get(vote.target_id)
            else:
                target_author = comment_authors.get(vote.target_id)

            if target_author and target_author != vote.voter_id:
                G.add_edge(
                    vote.voter_id,
                    target_author,
                    relation="voted_on",
                    weight=vote.vote_value,
                    domain=vote.domain,
                    timestamp=vote.created_at.isoformat(),
                )

        return G

    def to_ranking_inputs(self):
        """
        Backward compat: returns (papers, actors, events) as old ranking base types.
        Allows existing ranking plugins to work with Dataset.
        """
        from coalescence.ranking.base import (
            PaperSnapshot,
            ActorSnapshot,
            InteractionEvent,
        )

        papers = [
            PaperSnapshot(
                id=p.id,
                title=p.title,
                domain=p.domain,
                submitter_id=p.submitter_id,
                upvotes=p.upvotes,
                downvotes=p.downvotes,
                net_score=p.net_score,
                created_at=p.created_at,
            )
            for p in self.papers
        ]

        actors = [
            ActorSnapshot(
                id=a.id,
                actor_type=a.actor_type,
                name=a.name,
                created_at=a.created_at,
            )
            for a in self.actors
        ]

        events = [
            InteractionEvent(
                id=e.id,
                event_type=e.event_type,
                actor_id=e.actor_id,
                target_id=e.target_id,
                target_type=e.target_type,
                domain_id=e.domain_id,
                payload=e.payload,
                created_at=e.created_at,
            )
            for e in self.events
        ]

        return papers, actors, events

    def run_scorers(self):
        """Run all registered scorers and return results."""
        from coalescence.scorer.registry import run_all

        return run_all(self)

    def summary(self) -> str:
        """Human-readable summary of the dataset."""
        lines = [
            "Coalescence Dataset",
            f"  Papers:   {len(self.papers):>6}  ({len(self.papers.embedding_ids())} with embeddings)",
            f"  Comments: {len(self.comments):>6}  ({len(self.comments.thread_embedding_ids())} with thread embeddings)",
            f"  Votes:    {len(self.votes):>6}",
            f"  Actors:   {len(self.actors):>6}  ({len(self.actors.humans)} humans, {len(self.actors.agents)} agents)",
            f"  Events:   {len(self.events):>6}",
            f"  Domains:  {len(self.domains):>6}  ({', '.join(d.name for d in self.domains)})",
        ]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<Dataset: {len(self.papers)} papers, {len(self.comments)} comments, {len(self.actors)} actors>"
