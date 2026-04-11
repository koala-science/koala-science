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
        """Store embedding in pgvector column and sync to Qdrant."""
        activity.logger.info(f"Storing embedding for paper: {paper_id}")

        import uuid
        from sqlalchemy import select, update
        from sqlalchemy.orm import joinedload
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Paper

        async with AsyncSessionLocal() as session:
            # Store in pgvector
            await session.execute(
                update(Paper)
                .where(Paper.id == uuid.UUID(paper_id))
                .values(embedding=embedding)
            )
            await session.commit()

            # Sync to Qdrant
            try:
                result = await session.execute(
                    select(Paper).options(joinedload(Paper.submitter))
                    .where(Paper.id == uuid.UUID(paper_id))
                )
                paper = result.scalar_one_or_none()
                if paper:
                    from app.core.qdrant import upsert_paper
                    created_at = int(paper.created_at.timestamp()) if paper.created_at else 0
                    upsert_paper(
                        paper.id, embedding,
                        title=paper.title,
                        abstract=paper.abstract or "",
                        domains=paper.domains or [],
                        submitter_id=str(paper.submitter_id),
                        submitter_name=paper.submitter.name if paper.submitter else None,
                        arxiv_id=paper.arxiv_id,
                        created_at=created_at,
                        net_score=paper.net_score or 0,
                        preview_image_url=paper.preview_image_url,
                    )
                    activity.logger.info(f"Synced paper {paper_id} to Qdrant")
            except Exception as e:
                activity.logger.warning(f"Qdrant sync failed for paper {paper_id}: {e}")

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
