"""
ThreadEmbeddingWorkflow: Assemble a comment thread and generate/store its embedding.

Triggered when a comment is created or a reply is added to an existing thread.
The embedding is stored on the root comment of the thread.
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
        """Store the thread embedding on the root comment."""
        activity.logger.info(f"Storing thread embedding for root comment: {root_comment_id}")

        import uuid
        from sqlalchemy import update
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Comment

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Comment)
                .where(Comment.id == uuid.UUID(root_comment_id))
                .values(thread_embedding=embedding)
            )
            await session.commit()

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
