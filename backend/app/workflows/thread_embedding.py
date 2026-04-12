"""
ThreadEmbeddingWorkflow: Assemble a comment thread and generate/store its embedding.

Triggered when a comment is created or a reply is added to an existing thread.
The embedding is stored in Qdrant only.
"""
from datetime import timedelta

from temporalio import activity, workflow


class ThreadEmbeddingActivities:

    @activity.defn
    async def assemble_and_embed_thread(self, comment_id: str) -> dict | None:
        """
        Assemble thread text from root, generate embedding, return
        {root_comment_id, embedding} or None on failure.
        """
        activity.logger.info(f"Assembling thread for comment: {comment_id}")

        from app.db.session import AsyncSessionLocal
        from app.core.thread_assembler import assemble_thread_text
        from app.core.embeddings import generate_embedding

        async with AsyncSessionLocal() as session:
            result = await assemble_thread_text(comment_id, session)

        if not result:
            activity.logger.warning(f"Could not assemble thread for comment {comment_id}")
            return None

        root_id, text = result
        activity.logger.info(f"Thread assembled ({len(text)} chars), root: {root_id}")

        embedding = await generate_embedding(text)
        if not embedding:
            return None

        return {"root_comment_id": root_id, "embedding": embedding}

    @activity.defn
    async def store_thread_embedding(self, root_comment_id: str, embedding: list[float]) -> bool:
        """Store the thread embedding in Qdrant."""
        activity.logger.info(f"Storing thread embedding for root comment: {root_comment_id}")

        import uuid
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Comment

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Comment)
                .options(joinedload(Comment.author), joinedload(Comment.paper))
                .where(Comment.id == uuid.UUID(root_comment_id))
            )
            comment = result.scalar_one_or_none()
            if not comment:
                activity.logger.warning(f"Root comment {root_comment_id} not found")
                return False

            from app.core.qdrant import upsert_thread
            created_at = int(comment.created_at.timestamp()) if comment.created_at else 0
            upsert_thread(
                comment.id, embedding,
                paper_id=str(comment.paper_id),
                paper_title=comment.paper.title if comment.paper else "",
                paper_domains=comment.paper.domains if comment.paper else [],
                author_id=str(comment.author_id),
                author_name=comment.author.name if comment.author else None,
                content_preview=(comment.content_markdown or "")[:500],
                created_at=created_at,
            )
            activity.logger.info(f"Stored thread {root_comment_id} in Qdrant")

        return True


@workflow.defn
class ThreadEmbeddingWorkflow:

    @workflow.run
    async def run(self, comment_id: str) -> bool:
        result = await workflow.execute_activity_method(
            ThreadEmbeddingActivities.assemble_and_embed_thread,
            comment_id,
            start_to_close_timeout=timedelta(seconds=60),
        )

        if result is None:
            return False

        await workflow.execute_activity_method(
            ThreadEmbeddingActivities.store_thread_embedding,
            args=[result["root_comment_id"], result["embedding"]],
            start_to_close_timeout=timedelta(seconds=15),
        )

        return True
