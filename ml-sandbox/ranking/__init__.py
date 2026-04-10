# Backward-compat shim — imports from new location
from coalescence.ranking.base import RankingPlugin, RankingReport, PaperSnapshot, ActorSnapshot, InteractionEvent

__all__ = ["RankingPlugin", "RankingReport", "PaperSnapshot", "ActorSnapshot", "InteractionEvent"]
