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
    PaperCollection, CommentCollection, VoteCollection,
    ActorCollection, EventCollection, DomainCollection,
)
from coalescence.data.loader import (
    load_papers, load_comments, load_votes,
    load_actors, load_events, load_domains,
    hydrate_last_activity,
)


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
        manifest: dict | None = None,
    ):
        self.papers = papers
        self.comments = comments
        self.votes = votes
        self.actors = actors
        self.events = events
        self.domains = domains
        self.manifest = manifest or {}

    @classmethod
    def load(cls, path: str) -> Dataset:
        """
        Load a dump directory containing JSONL files.
        Reads manifest.json if present, otherwise auto-discovers files.
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

        # Hydrate last_activity_at from events
        hydrate_last_activity(papers, comments, actors, events)

        counts = {
            "papers": len(papers),
            "comments": len(comments),
            "votes": len(votes),
            "actors": len(actors),
            "events": len(events),
            "domains": len(domains),
        }
        print(f"Dataset loaded: {', '.join(f'{v} {k}' for k, v in counts.items())}")

        return cls(
            papers=PaperCollection(papers),
            comments=CommentCollection(comments),
            votes=VoteCollection(votes),
            actors=ActorCollection(actors),
            events=EventCollection(events),
            domains=DomainCollection(domains),
            manifest=manifest,
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
            G.add_node(actor.id, type=actor.actor_type, name=actor.name, reputation=actor.reputation_score)

        # Paper submitter lookup
        paper_submitters = {p.id: p.submitter_id for p in self.papers}

        # Comment author lookup
        comment_authors = {c.id: c.author_id for c in self.comments}

        # Edges from comments
        for comment in self.comments:
            # Comment on paper → edge to paper submitter
            submitter = paper_submitters.get(comment.paper_id)
            if submitter and submitter != comment.author_id:
                G.add_edge(comment.author_id, submitter,
                           relation="commented_on", domain=comment.paper_domain,
                           timestamp=comment.created_at.isoformat())

            # Reply → edge to parent author
            if comment.parent_id:
                parent_author = comment_authors.get(comment.parent_id)
                if parent_author and parent_author != comment.author_id:
                    G.add_edge(comment.author_id, parent_author,
                               relation="replied_to", domain=comment.paper_domain,
                               timestamp=comment.created_at.isoformat())

        # Edges from votes
        for vote in self.votes:
            if vote.target_type == "PAPER":
                target_author = paper_submitters.get(vote.target_id)
            else:
                target_author = comment_authors.get(vote.target_id)

            if target_author and target_author != vote.voter_id:
                G.add_edge(vote.voter_id, target_author,
                           relation="voted_on", weight=vote.vote_value,
                           domain=vote.domain,
                           timestamp=vote.created_at.isoformat())

        return G

    def to_ranking_inputs(self):
        """
        Backward compat: returns (papers, actors, events) as old ranking base types.
        Allows existing ranking plugins to work with Dataset.
        """
        from coalescence.ranking.base import PaperSnapshot, ActorSnapshot, InteractionEvent

        papers = [
            PaperSnapshot(
                id=p.id, title=p.title, domain=p.domain,
                submitter_id=p.submitter_id,
                upvotes=p.upvotes, downvotes=p.downvotes, net_score=p.net_score,
                created_at=p.created_at,
            )
            for p in self.papers
        ]

        actors = [
            ActorSnapshot(
                id=a.id, actor_type=a.actor_type, name=a.name,
                created_at=a.created_at,
            )
            for a in self.actors
        ]

        events = [
            InteractionEvent(
                id=e.id, event_type=e.event_type, actor_id=e.actor_id,
                target_id=e.target_id, target_type=e.target_type,
                domain_id=e.domain_id, payload=e.payload,
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
            f"Coalescence Dataset",
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
