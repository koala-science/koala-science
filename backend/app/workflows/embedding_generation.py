"""
EmbeddingGenerationWorkflow: Generate and store vector embeddings for papers.
Uses Gemini embedding model (768 dims).
"""
from datetime import timedelta

from temporalio import activity, workflow


class EmbeddingActivities:

    @activity.defn
    async def generate_embedding(self, text: str) -> list[float] | None:
        """Generate vector embedding from text using Gemini."""
        activity.logger.info(f"Generating embedding for text ({len(text)} chars)")
        from app.core.embeddings import generate_embedding
        return await generate_embedding(text)

    @activity.defn
    async def store_embedding(self, paper_id: str, embedding: list[float]) -> bool:
        """Store embedding in pgvector column on Paper record."""
        activity.logger.info(f"Storing embedding for paper: {paper_id}")

        import uuid
        from sqlalchemy import update
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Paper

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Paper)
                .where(Paper.id == uuid.UUID(paper_id))
                .values(embedding=embedding)
            )
            await session.commit()

        return True


@workflow.defn
class EmbeddingGenerationWorkflow:

    @workflow.run
    async def run(self, paper_id: str, text: str) -> bool:
        embedding = await workflow.execute_activity_method(
            EmbeddingActivities.generate_embedding,
            text,
            start_to_close_timeout=timedelta(seconds=60),
        )

        if embedding is None:
            return False

        await workflow.execute_activity_method(
            EmbeddingActivities.store_embedding,
            args=[paper_id, embedding],
            start_to_close_timeout=timedelta(seconds=15),
        )

        return True
