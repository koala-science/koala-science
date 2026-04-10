"""
RankingCacheRefreshWorkflow: Precompute feed rankings and cache in Redis.
Scheduled every 5 minutes.
"""
import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow


@dataclass
class RankingCacheResult:
    domains_cached: int
    sort_modes_computed: list[str]


EPOCH = 1134028003


class RankingActivities:

    @activity.defn
    async def refresh_feed_cache(self) -> dict:
        """Precompute Hot/Top/New/Controversial for all domains → Redis."""
        activity.logger.info("Refreshing feed ranking cache")

        import math
        import redis.asyncio as redis
        from sqlalchemy import select, func
        from app.core.config import settings
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Paper, Domain

        r = redis.from_url(settings.REDIS_URL)
        domains_cached = 0

        async with AsyncSessionLocal() as session:
            # Get all domains
            result = await session.execute(select(Domain))
            domains = result.scalars().all()

            for domain in domains:
                # Fetch papers in this domain
                paper_result = await session.execute(
                    select(Paper).where(Paper.domain == domain.name)
                )
                papers = paper_result.scalars().all()

                if not papers:
                    continue

                # Compute rankings for each sort mode
                paper_dicts = []
                for p in papers:
                    epoch_seconds = p.created_at.timestamp() if p.created_at else 0
                    hot_score = (
                        (1 if p.net_score > 0 else -1 if p.net_score < 0 else 0)
                        * math.log10(max(abs(p.net_score), 1))
                        + (epoch_seconds - EPOCH) / 45000
                    )
                    controversial = (
                        (p.upvotes + p.downvotes)
                        / max(abs(p.upvotes - p.downvotes), 1)
                        if (p.upvotes + p.downvotes) > 0 else 0
                    )
                    paper_dicts.append({
                        "id": str(p.id),
                        "title": p.title,
                        "domain": p.domain,
                        "net_score": p.net_score,
                        "hot_score": hot_score,
                        "controversial_score": controversial,
                        "created_at": p.created_at.isoformat() if p.created_at else "",
                    })

                # Store sorted lists in Redis
                for sort_mode, key_func in [
                    ("hot", lambda x: x["hot_score"]),
                    ("top", lambda x: x["net_score"]),
                    ("new", lambda x: x["created_at"]),
                    ("controversial", lambda x: x["controversial_score"]),
                ]:
                    sorted_papers = sorted(paper_dicts, key=key_func, reverse=True)
                    cache_key = f"feed:{domain.name}:{sort_mode}"
                    await r.set(cache_key, json.dumps(sorted_papers), ex=600)  # 10 min TTL

                domains_cached += 1

        await r.aclose()

        return {
            "domains_cached": domains_cached,
            "sort_modes_computed": ["hot", "top", "new", "controversial"],
        }


@workflow.defn
class RankingCacheRefreshWorkflow:

    @workflow.run
    async def run(self) -> RankingCacheResult:
        result = await workflow.execute_activity_method(
            RankingActivities.refresh_feed_cache,
            start_to_close_timeout=timedelta(minutes=2),
        )

        return RankingCacheResult(
            domains_cached=result["domains_cached"],
            sort_modes_computed=result["sort_modes_computed"],
        )
