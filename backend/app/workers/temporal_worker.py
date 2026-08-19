"""
Temporal worker process for Coalescence background workflows.

Run with: python -m app.workers.temporal_worker
"""
import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from app.workflows.embedding_generation import EmbeddingGenerationWorkflow, EmbeddingActivities
from app.workflows.data_export import IncrementalEventExportWorkflow, FullDataDumpWorkflow, DataExportActivities

TASK_QUEUE = "coalescence-workflows"


async def main():
    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
    client = await Client.connect(temporal_host)

    # Instantiate activity classes (they hold dependencies like DB sessions, Redis, etc.)
    embedding_activities = EmbeddingActivities()
    export_activities = DataExportActivities()

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            EmbeddingGenerationWorkflow,
            IncrementalEventExportWorkflow,
            FullDataDumpWorkflow,
        ],
        activities=[
            embedding_activities.generate_embedding,
            embedding_activities.store_embedding,
            export_activities.export_incremental_events,
            export_activities.export_full_papers,
            export_activities.export_full_arguments,
            export_activities.export_full_events,
            export_activities.export_full_actors,
            export_activities.export_full_domains,
        ],
    )

    print(f"Temporal worker started, listening on task queue: {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
