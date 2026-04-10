"""
Comment depth ranking: rewards comments with more engagement.
Longer, more detailed comments contribute more to paper and actor scores.
"""
from collections import defaultdict

from ml_sandbox.ranking.base import (
    RankingPlugin, PaperSnapshot, ActorSnapshot, InteractionEvent,
)


COMMENT_EVENTS = {"COMMENT_POSTED"}


class AttachmentBoostRanking(RankingPlugin):
    """Legacy name kept for plugin registry compatibility."""

    @property
    def name(self) -> str:
        return "comment_depth"

    def score_paper(self, paper: PaperSnapshot, interactions: list[InteractionEvent]) -> float:
        comment_count = sum(
            1 for e in interactions
            if e.event_type in COMMENT_EVENTS and e.target_id == paper.id
        )
        vote_score = float(paper.net_score)
        return comment_count + vote_score

    def score_actor(self, actor: ActorSnapshot, interactions: list[InteractionEvent]) -> float:
        comments = 0
        net_validation = 0.0

        comment_authors: dict[str, str] = {}
        for event in interactions:
            if event.event_type in COMMENT_EVENTS and event.target_id:
                comment_authors[event.target_id] = event.actor_id

        for event in interactions:
            if event.event_type in COMMENT_EVENTS and event.actor_id == actor.id:
                comments += 1
            elif event.event_type == "VOTE_CAST" and event.target_type == "COMMENT":
                author = comment_authors.get(event.target_id or "")
                if author == actor.id:
                    net_validation += (event.payload or {}).get("vote_value", 0)

        return max(0.0, comments + net_validation)
