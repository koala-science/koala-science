"""
ReputationComputeWorkflow: Periodic recomputation of domain authority scores.
Scheduled to run every 15 minutes via Temporal schedule.

Formula:
    authority = (base_score + community_validation) * decay_factor

Where:
    base_score = count of comments in domain
    community_validation = sum of net_score on actor's comments in domain
    decay_factor = e^(-λ * days_since_last_contribution), λ = 0.01
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from temporalio import activity, workflow

DECAY_LAMBDA = 0.01  # half-life ~69 days
DORMANT_THRESHOLD_DAYS = 180  # 6 months


@dataclass
class ReputationComputeResult:
    actors_updated: int
    domains_processed: int


class ReputationActivities:

    @activity.defn
    async def compute_domain_authorities(self) -> dict:
        """Recompute all DomainAuthority scores."""
        activity.logger.info("Computing domain authorities for all actors")

        from sqlalchemy import select, func, and_
        from app.db.session import AsyncSessionLocal
        from app.models.platform import (
            Comment, Paper, Domain, DomainAuthority, Vote, TargetType,
        )

        actors_updated = 0
        domains_processed = 0
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            domain_result = await session.execute(select(Domain))
            domains = domain_result.scalars().all()

            for domain in domains:
                domains_processed += 1

                # Find all actors who have commented on papers in this domain
                commenter_query = (
                    select(
                        Comment.author_id,
                        func.count(Comment.id).label("total_comments"),
                        func.sum(Comment.net_score).label("community_validation"),
                        func.max(Comment.created_at).label("last_contribution"),
                    )
                    .join(Paper, Comment.paper_id == Paper.id)
                    .where(Paper.domain == domain.name)
                    .group_by(Comment.author_id)
                )

                result = await session.execute(commenter_query)
                rows = result.all()

                for row in rows:
                    author_id = row.author_id
                    total_comments = row.total_comments or 0
                    community_validation = row.community_validation or 0
                    last_contribution = row.last_contribution

                    base_score = total_comments

                    # Decay factor
                    if last_contribution:
                        days_since = (now - last_contribution.replace(tzinfo=timezone.utc)).days
                        decay_factor = math.exp(-DECAY_LAMBDA * days_since)

                        if days_since > DORMANT_THRESHOLD_DAYS:
                            decay_factor = 0.0
                    else:
                        decay_factor = 1.0

                    authority_score = (base_score + community_validation) * decay_factor
                    authority_score = max(0.0, authority_score)

                    # Count votes received on comments
                    upvotes_result = await session.execute(
                        select(func.count())
                        .select_from(Vote)
                        .join(Comment, and_(
                            Vote.target_id == Comment.id,
                            Vote.target_type == TargetType.COMMENT,
                        ))
                        .join(Paper, Comment.paper_id == Paper.id)
                        .where(
                            Comment.author_id == author_id,
                            Paper.domain == domain.name,
                            Vote.vote_value > 0,
                        )
                    )
                    total_up = upvotes_result.scalar() or 0

                    downvotes_result = await session.execute(
                        select(func.count())
                        .select_from(Vote)
                        .join(Comment, and_(
                            Vote.target_id == Comment.id,
                            Vote.target_type == TargetType.COMMENT,
                        ))
                        .join(Paper, Comment.paper_id == Paper.id)
                        .where(
                            Comment.author_id == author_id,
                            Paper.domain == domain.name,
                            Vote.vote_value < 0,
                        )
                    )
                    total_down = downvotes_result.scalar() or 0

                    # Upsert DomainAuthority
                    existing = await session.execute(
                        select(DomainAuthority).where(
                            DomainAuthority.actor_id == author_id,
                            DomainAuthority.domain_id == domain.id,
                        )
                    )
                    da = existing.scalar_one_or_none()

                    if da:
                        da.authority_score = authority_score
                        da.total_reviews = total_comments
                        da.total_upvotes_received = total_up
                        da.total_downvotes_received = total_down
                    else:
                        da = DomainAuthority(
                            actor_id=author_id,
                            domain_id=domain.id,
                            authority_score=authority_score,
                            total_reviews=total_comments,
                            total_upvotes_received=total_up,
                            total_downvotes_received=total_down,
                        )
                        session.add(da)

                    actors_updated += 1

            await session.commit()

        activity.logger.info(
            f"Reputation compute done: {actors_updated} actors updated across {domains_processed} domains"
        )
        return {"actors_updated": actors_updated, "domains_processed": domains_processed}


@workflow.defn
class ReputationComputeWorkflow:

    @workflow.run
    async def run(self) -> ReputationComputeResult:
        result = await workflow.execute_activity_method(
            ReputationActivities.compute_domain_authorities,
            start_to_close_timeout=timedelta(minutes=5),
        )

        return ReputationComputeResult(
            actors_updated=result["actors_updated"],
            domains_processed=result["domains_processed"],
        )
