"""
Weighted log ranking: production default.
vote_weight = 1.0 + log2(1 + authority)
Paper score = sum of weighted votes.
"""
import math
from collections import defaultdict

from coalescence.ranking.base import (
    RankingPlugin, PaperSnapshot, ActorSnapshot, InteractionEvent,
)

COMMENT_EVENTS = {"COMMENT_POSTED"}


class WeightedLogRanking(RankingPlugin):

    @property
    def name(self) -> str:
        return "weighted_log"

    def score_paper(self, paper: PaperSnapshot, interactions: list[InteractionEvent]) -> float:
        actor_authorities = self._compute_authorities(interactions)

        score = 0.0
        for event in interactions:
            if event.event_type == "VOTE_CAST" and event.target_id == paper.id:
                voter_authority = actor_authorities.get(event.actor_id, 0.0)
                weight = 1.0 + math.log2(1 + voter_authority)
                vote_value = (event.payload or {}).get("vote_value", 1)
                score += vote_value * weight
        return score

    def score_actor(self, actor: ActorSnapshot, interactions: list[InteractionEvent]) -> float:
        authorities = self._compute_authorities(interactions)
        return authorities.get(actor.id, 0.0)

    def _compute_authorities(self, interactions: list[InteractionEvent]) -> dict[str, float]:
        comment_counts: dict[str, int] = defaultdict(int)
        net_scores: dict[str, float] = defaultdict(float)

        comment_authors: dict[str, str] = {}
        for event in interactions:
            if event.event_type in COMMENT_EVENTS and event.target_id:
                comment_authors[event.target_id] = event.actor_id

        for event in interactions:
            if event.event_type in COMMENT_EVENTS:
                comment_counts[event.actor_id] += 1
            elif event.event_type == "VOTE_CAST" and event.target_type == "COMMENT":
                author = comment_authors.get(event.target_id or "")
                if author:
                    vote_value = (event.payload or {}).get("vote_value", 0)
                    net_scores[author] += vote_value

        all_actors = set(list(comment_counts.keys()) + list(net_scores.keys()))
        authorities = {}
        for actor_id in all_actors:
            base = comment_counts.get(actor_id, 0)
            validation = net_scores.get(actor_id, 0)
            authorities[actor_id] = max(0.0, base + validation)

        return authorities
