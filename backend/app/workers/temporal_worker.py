"""
Temporal worker process for Coalescence background workflows.

Run with: python -m app.workers.temporal_worker
"""
import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from app.workflows.arxiv_ingestion import ArxivIngestionWorkflow, ArxivIngestionActivities
from app.workflows.embedding_generation import EmbeddingGenerationWorkflow, EmbeddingActivities
from app.workflows.data_export import IncrementalEventExportWorkflow, FullDataDumpWorkflow, DataExportActivities
from app.workflows.thread_embedding import ThreadEmbeddingWorkflow, ThreadEmbeddingActivities

TASK_QUEUE = "coalescence-workflows"


async def main():
    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
    client = await Client.connect(temporal_host)

    # Instantiate activity classes (they hold dependencies like DB sessions, Redis, etc.)
    arxiv_activities = ArxivIngestionActivities()
    embedding_activities = EmbeddingActivities()
    export_activities = DataExportActivities()
    thread_embedding_activities = ThreadEmbeddingActivities()

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            ArxivIngestionWorkflow,
            EmbeddingGenerationWorkflow,
            IncrementalEventExportWorkflow,
            FullDataDumpWorkflow,
            ThreadEmbeddingWorkflow,
        ],
        activities=[
            arxiv_activities.fetch_arxiv_metadata,
            arxiv_activities.download_pdf,
            arxiv_activities.extract_text_from_pdf,
            arxiv_activities.create_paper_record,
            arxiv_activities.extract_preview_image,
            embedding_activities.generate_embedding,
            embedding_activities.store_embedding,
            export_activities.export_incremental_events,
            export_activities.export_full_papers,
            export_activities.export_full_comments,
            export_activities.export_full_events,
            export_activities.export_full_actors,
            export_activities.export_full_domains,
            thread_embedding_activities.assemble_and_embed_thread,
            thread_embedding_activities.store_thread_embedding,
        ],
    )

    print(f"Temporal worker started, listening on task queue: {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
