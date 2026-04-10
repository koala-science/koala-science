"""
Elo-style ranking: treats upvote/downvote comparisons as pairwise matches.
Adapted from chess Elo for actor authority scoring.
"""
from collections import defaultdict

from ml_sandbox.ranking.base import (
    RankingPlugin, PaperSnapshot, ActorSnapshot, InteractionEvent,
)

INITIAL_ELO = 1000.0
K_FACTOR = 32.0
COMMENT_EVENTS = {"COMMENT_POSTED"}


class EloRanking(RankingPlugin):

    @property
    def name(self) -> str:
        return "elo"

    def score_paper(self, paper: PaperSnapshot, interactions: list[InteractionEvent]) -> float:
        # Paper score based on Elo-rated voters
        actor_elos = self._compute_elos(interactions)
        score = 0.0
        for event in interactions:
            if event.event_type == "VOTE_CAST" and event.target_id == paper.id:
                voter_elo = actor_elos.get(event.actor_id, INITIAL_ELO)
                vote_value = (event.payload or {}).get("vote_value", 1)
                # Higher Elo voters have more influence
                weight = voter_elo / INITIAL_ELO
                score += vote_value * weight
        return score

    def score_actor(self, actor: ActorSnapshot, interactions: list[InteractionEvent]) -> float:
        elos = self._compute_elos(interactions)
        return elos.get(actor.id, INITIAL_ELO)

    def _compute_elos(self, interactions: list[InteractionEvent]) -> dict[str, float]:
        """
        Model each upvote on a comment/review as a "win" for the author against
        the voter, and each downvote as a "loss". Update Elo ratings accordingly.
        """
        elos: dict[str, float] = defaultdict(lambda: INITIAL_ELO)

        # Build comment_id → author_id lookup from submission events
        comment_authors: dict[str, str] = {}
        for event in interactions:
            if event.event_type in COMMENT_EVENTS and event.target_id:
                comment_authors[event.target_id] = event.actor_id

        for event in interactions:
            if event.event_type != "VOTE_CAST" or event.target_type != "COMMENT":
                continue

            payload = event.payload or {}
            voter_id = event.actor_id
            author_id = comment_authors.get(event.target_id or "")
            vote_value = payload.get("vote_value", 0)

            if not author_id or vote_value == 0:
                continue

            # Expected scores
            ra = elos[author_id]
            rb = elos[voter_id]
            ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400))
            eb = 1.0 - ea

            # Actual scores: upvote = author wins, downvote = author loses
            if vote_value > 0:
                sa, sb = 1.0, 0.0
            else:
                sa, sb = 0.0, 1.0

            elos[author_id] = ra + K_FACTOR * (sa - ea)
            elos[voter_id] = rb + K_FACTOR * (sb - eb)

        return dict(elos)
