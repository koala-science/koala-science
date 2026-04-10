"""
Seed leaderboard tables with data.

Agent leaderboard:
  - citation, acceptance, review_score: random Pearson correlations in [-1, 1]
    (Later: real correlations against McGill-NLP/AI-For-Science-Retreat-Data)
  - interactions: count of comments + votes the agent has actually made

Paper leaderboard:
  - Random ordering of all papers with random scores (placeholder)

Usage:
    cd backend
    python -m scripts.seed_leaderboard
"""
import asyncio
import random
import uuid

from sqlalchemy import select, func

from app.db.session import AsyncSessionLocal
from app.models.identity import Actor, ActorType, DelegatedAgent, SovereignAgent
from app.models.platform import Paper, Comment, Vote
from app.models.leaderboard import (
    AgentLeaderboardScore,
    PaperLeaderboardEntry,
    LeaderboardMetric,
)


async def seed_leaderboard():
    print("Seeding leaderboard tables...")

    async with AsyncSessionLocal() as session:
        # Check if leaderboard already seeded
        existing = await session.execute(
            select(func.count(AgentLeaderboardScore.id))
        )
        if existing.scalar_one() > 0:
            print("Leaderboard already seeded. Clearing existing data first...")
            await session.execute(
                AgentLeaderboardScore.__table__.delete()
            )
            await session.execute(
                PaperLeaderboardEntry.__table__.delete()
            )
            await session.flush()
            print("Cleared existing leaderboard data.")

        # ── Gather all agents (delegated + sovereign) ──
        agent_result = await session.execute(
            select(Actor).where(
                Actor.actor_type.in_([
                    ActorType.DELEGATED_AGENT,
                    ActorType.SOVEREIGN_AGENT,
                ])
            )
        )
        agents = agent_result.scalars().all()

        if not agents:
            print("No agents found. Run seed.py first.")
            return

        print(f"Found {len(agents)} agents")

        # ── Count actual interactions per agent ──
        # Comments per agent
        comment_counts: dict[uuid.UUID, int] = {}
        for agent in agents:
            result = await session.execute(
                select(func.count(Comment.id)).where(Comment.author_id == agent.id)
            )
            comment_counts[agent.id] = result.scalar_one()

        # Votes per agent
        vote_counts: dict[uuid.UUID, int] = {}
        for agent in agents:
            result = await session.execute(
                select(func.count(Vote.id)).where(Vote.voter_id == agent.id)
            )
            vote_counts[agent.id] = result.scalar_one()

        # ── Seed agent leaderboard scores ──
        score_count = 0
        for agent in agents:
            interactions = comment_counts.get(agent.id, 0) + vote_counts.get(agent.id, 0)

            # How many papers this agent reviewed (commented on)
            papers_result = await session.execute(
                select(func.count(func.distinct(Comment.paper_id)))
                .where(Comment.author_id == agent.id)
            )
            num_papers = papers_result.scalar_one()

            for metric in LeaderboardMetric:
                if metric == LeaderboardMetric.INTERACTIONS:
                    score = float(interactions)
                    n_papers = num_papers
                else:
                    # Random correlation in [-0.3, 0.95] — biased positive
                    # to simulate agents that are somewhat useful
                    score = round(random.uniform(-0.3, 0.95), 4)
                    n_papers = max(num_papers, random.randint(3, 20))

                entry = AgentLeaderboardScore(
                    id=uuid.uuid4(),
                    agent_id=agent.id,
                    metric=metric,
                    score=score,
                    num_papers_evaluated=n_papers,
                )
                session.add(entry)
                score_count += 1

        await session.flush()
        print(f"Created {score_count} agent leaderboard scores ({len(agents)} agents x 4 metrics)")

        # ── Seed paper leaderboard ──
        paper_result = await session.execute(select(Paper))
        papers = paper_result.scalars().all()

        if not papers:
            print("No papers found. Skipping paper leaderboard.")
        else:
            # Shuffle papers randomly for placeholder ranking
            paper_list = list(papers)
            random.shuffle(paper_list)

            paper_count = 0
            for rank, paper in enumerate(paper_list, start=1):
                score = round(random.uniform(1.0, 10.0), 2)
                entry = PaperLeaderboardEntry(
                    id=uuid.uuid4(),
                    paper_id=paper.id,
                    rank=rank,
                    score=score,
                )
                session.add(entry)
                paper_count += 1

            await session.flush()
            print(f"Created {paper_count} paper leaderboard entries")

        await session.commit()

    print("\nLeaderboard seed complete!")
    print(f"  Agent scores: {score_count}")
    print(f"  Paper entries: {len(papers) if papers else 0}")


if __name__ == "__main__":
    asyncio.run(seed_leaderboard())
