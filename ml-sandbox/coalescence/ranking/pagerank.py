"""
PageRank-style authority propagation on the actor-comment graph.
Actors that receive votes from high-authority actors gain more authority.
"""
from collections import defaultdict

from coalescence.ranking.base import (
    RankingPlugin, PaperSnapshot, ActorSnapshot, InteractionEvent,
)

COMMENT_EVENTS = {"COMMENT_POSTED"}


class PageRankRanking(RankingPlugin):

    def __init__(self, damping: float = 0.85, iterations: int = 20):
        self.damping = damping
        self.iterations = iterations

    @property
    def name(self) -> str:
        return "pagerank"

    def score_paper(self, paper: PaperSnapshot, interactions: list[InteractionEvent]) -> float:
        authorities = self._compute_pagerank(interactions)
        score = 0.0
        for event in interactions:
            if event.event_type == "VOTE_CAST" and event.target_id == paper.id:
                vote_value = (event.payload or {}).get("vote_value", 1)
                voter_auth = authorities.get(event.actor_id, 1.0 / max(len(authorities), 1))
                score += vote_value * voter_auth * 100  # Scale up
        return score

    def score_actor(self, actor: ActorSnapshot, interactions: list[InteractionEvent]) -> float:
        authorities = self._compute_pagerank(interactions)
        return authorities.get(actor.id, 0.0)

    def _compute_pagerank(self, interactions: list[InteractionEvent]) -> dict[str, float]:
        """
        Build a directed graph: voter → comment_author (edge = upvote).
        Run PageRank to propagate authority.
        """
        # Build comment_id → author_id lookup
        comment_authors: dict[str, str] = {}
        for event in interactions:
            if event.event_type in COMMENT_EVENTS and event.target_id:
                comment_authors[event.target_id] = event.actor_id

        # Build adjacency: voter_id → set of actors they upvoted
        graph: dict[str, set[str]] = defaultdict(set)
        all_actors: set[str] = set()

        for event in interactions:
            all_actors.add(event.actor_id)
            if event.event_type == "VOTE_CAST" and event.target_type == "COMMENT":
                payload = event.payload or {}
                author = comment_authors.get(event.target_id or "")
                vote_value = payload.get("vote_value", 0)
                if author and vote_value > 0:
                    graph[event.actor_id].add(author)
                    all_actors.add(author)

        if not all_actors:
            return {}

        n = len(all_actors)
        actors = list(all_actors)
        rank = {a: 1.0 / n for a in actors}

        for _ in range(self.iterations):
            new_rank = {}
            for actor in actors:
                # Sum contributions from actors that link to this actor
                incoming = 0.0
                for other in actors:
                    if actor in graph.get(other, set()):
                        out_degree = len(graph[other])
                        if out_degree > 0:
                            incoming += rank[other] / out_degree

                new_rank[actor] = (1 - self.damping) / n + self.damping * incoming
            rank = new_rank

        return rank
