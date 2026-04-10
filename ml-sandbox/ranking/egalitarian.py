"""
Egalitarian ranking: 1 vote = 1 unit. The baseline model.
"""
from ml_sandbox.ranking.base import (
    RankingPlugin, PaperSnapshot, ActorSnapshot, InteractionEvent,
)

COMMENT_EVENTS = {"COMMENT_POSTED"}


class EgalitarianRanking(RankingPlugin):

    @property
    def name(self) -> str:
        return "egalitarian"

    def score_paper(self, paper: PaperSnapshot, interactions: list[InteractionEvent]) -> float:
        return float(paper.net_score)

    def score_actor(self, actor: ActorSnapshot, interactions: list[InteractionEvent]) -> float:
        # Count reviews and comments authored (reviews count as 1, comments as 0.5)
        score = 0.0
        for e in interactions:
            if e.event_type in COMMENT_EVENTS and e.actor_id == actor.id:
                score += 1.0
        return score
