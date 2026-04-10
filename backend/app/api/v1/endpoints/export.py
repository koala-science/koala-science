"""
Data export endpoints: live event queries + on-demand full dumps.
"""
import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.core.config import settings
from app.models.identity import Actor
from app.models.platform import InteractionEvent
from app.schemas.platform import (
    InteractionEventResponse,
    WorkflowTriggerResponse,
    WorkflowStatusResponse,
)

router = APIRouter()


@router.get("/events", response_model=List[InteractionEventResponse])
async def export_events(
    since: Optional[datetime] = None,
    event_type: Optional[str] = None,
    domain_id: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """
    Export interaction events. Requires authentication.
    Returns paginated events for offline analysis.
    """
    query = select(InteractionEvent).order_by(InteractionEvent.created_at.asc())

    if since:
        query = query.where(InteractionEvent.created_at >= since)
    if event_type:
        query = query.where(InteractionEvent.event_type == event_type)
    if domain_id:
        query = query.where(InteractionEvent.domain_id == domain_id)

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()

    return events


@router.post("/full-dump", response_model=WorkflowTriggerResponse, status_code=202)
async def trigger_full_dump(
    actor: Actor = Depends(get_current_actor),
):
    """
    Trigger a full data dump via Temporal workflow.
    Returns a workflow_id to poll for status.
    """
    from temporalio.client import Client

    try:
        temporal_client = await Client.connect(settings.TEMPORAL_HOST)
        workflow_id = f"full-dump-{uuid.uuid4().hex[:8]}"

        await temporal_client.start_workflow(
            "FullDataDumpWorkflow",
            id=workflow_id,
            task_queue="coalescence-workflows",
        )

        return {
            "status": "accepted",
            "workflow_id": workflow_id,
            "message": "Full data dump started. Poll /export/full-dump/{workflow_id} for status.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start dump: {e}")


@router.get("/full-dump/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_dump_status(
    workflow_id: str,
    actor: Actor = Depends(get_current_actor),
):
    """
    Check the status of a full data dump workflow.
    Returns file URLs when complete.
    """
    from temporalio.client import Client, WorkflowExecutionStatus

    try:
        temporal_client = await Client.connect(settings.TEMPORAL_HOST)
        handle = temporal_client.get_workflow_handle(workflow_id)
        desc = await handle.describe()

        if desc.status == WorkflowExecutionStatus.RUNNING:
            return {"status": "running", "workflow_id": workflow_id}

        if desc.status == WorkflowExecutionStatus.COMPLETED:
            result = await handle.result()
            return {
                "status": "completed",
                "workflow_id": workflow_id,
                "files": [
                    {"name": "papers.jsonl", "url": result.papers_path},
                    {"name": "comments.jsonl", "url": result.comments_path},
                    {"name": "events.jsonl", "url": result.events_path},
                    {"name": "actors.jsonl", "url": result.actors_path},
                    {"name": "votes.jsonl", "url": result.votes_path},
                    {"name": "domains.jsonl", "url": result.domains_path},
                ],
                "counts": {
                    "papers": result.papers_count,
                    "comments": result.comments_count,
                    "events": result.events_count,
                    "actors": result.actors_count,
                    "votes": result.votes_count,
                    "domains": result.domains_count,
                },
            }

        if desc.status == WorkflowExecutionStatus.FAILED:
            return {
                "status": "failed",
                "workflow_id": workflow_id,
                "error": "Workflow failed — check Temporal UI for details",
            }

        return {"status": str(desc.status), "workflow_id": workflow_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check status: {e}")
