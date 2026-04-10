"""
Data export workflows:
  - IncrementalEventExport: every 15 min, exports new events since last run
  - FullDataDumpWorkflow: on-demand or daily, exports papers, comments, events, actors
"""
import json
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from temporalio import activity, workflow


@dataclass
class IncrementalExportResult:
    file_path: str
    events_exported: int


@dataclass
class FullDumpResult:
    papers_path: str
    comments_path: str
    events_path: str
    actors_path: str
    votes_path: str
    domains_path: str
    papers_count: int
    comments_count: int
    events_count: int
    actors_count: int
    votes_count: int
    domains_count: int


def _json_default(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "hex"):
        return str(obj)
    return str(obj)


def _dumps(record: dict) -> str:
    return json.dumps(record, default=_json_default)


async def _write_and_upload(key: str, records: list[dict]) -> tuple[str, int]:
    """Write records to a temp file, upload via storage, return (url, count)."""
    from app.core.storage import storage

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        for r in records:
            tmp.write(_dumps(r) + "\n")
        tmp_path = tmp.name

    file_bytes = Path(tmp_path).read_bytes()
    url = await storage.save(key, file_bytes, content_type="application/jsonl")
    Path(tmp_path).unlink(missing_ok=True)
    return url, len(records)


class DataExportActivities:

    @activity.defn
    async def export_incremental_events(self) -> dict:
        """Export events since the last incremental export."""
        activity.logger.info("Running incremental event export")

        from datetime import datetime, timezone
        from sqlalchemy import select
        from app.db.session import AsyncSessionLocal
        from app.models.platform import InteractionEvent
        from app.core.storage import storage

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        last_export_key = "exports/incremental_last_id.txt"
        last_id_bytes = await storage.read(last_export_key)
        last_id = last_id_bytes.decode().strip() if last_id_bytes else None

        async with AsyncSessionLocal() as session:
            query = select(InteractionEvent).order_by(InteractionEvent.created_at.asc())

            if last_id:
                import uuid
                last_result = await session.execute(
                    select(InteractionEvent.created_at)
                    .where(InteractionEvent.id == uuid.UUID(last_id))
                )
                last_row = last_result.one_or_none()
                if last_row:
                    query = query.where(InteractionEvent.created_at > last_row[0])

            result = await session.execute(query)
            events = result.scalars().all()

        if not events:
            return {"file_path": "", "events_exported": 0}

        records = [_event_to_dict(e) for e in events]
        url, count = await _write_and_upload(f"exports/incremental/events_{timestamp}.jsonl", records)

        await storage.save(last_export_key, str(events[-1].id).encode(), content_type="text/plain")

        activity.logger.info(f"Incremental export: {count} new events")
        return {"file_path": url, "events_exported": count}

    @activity.defn
    async def export_full_papers(self, dump_id: str) -> dict:
        """Export all papers with embeddings."""
        activity.logger.info(f"Exporting papers for dump {dump_id}")

        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Paper

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Paper).options(joinedload(Paper.submitter))
            )
            papers = result.scalars().unique().all()

            records = [{
                "id": str(p.id),
                "title": p.title,
                "abstract": p.abstract,
                "domain": p.domain,
                "pdf_url": p.pdf_url,
                "github_repo_url": p.github_repo_url,
                "arxiv_id": p.arxiv_id,
                "authors": p.authors,
                "full_text_length": len(p.full_text) if p.full_text else 0,
                "submitter_id": str(p.submitter_id),
                "submitter_type": p.submitter.actor_type.value if p.submitter else None,
                "submitter_name": p.submitter.name if p.submitter else None,
                "upvotes": p.upvotes,
                "downvotes": p.downvotes,
                "net_score": p.net_score,
                "embedding": list(p.embedding) if p.embedding else None,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            } for p in papers]

        url, count = await _write_and_upload(f"exports/{dump_id}/papers.jsonl", records)
        activity.logger.info(f"Papers dump: {count}")
        return {"file_path": url, "count": count}

    @activity.defn
    async def export_full_comments(self, dump_id: str) -> dict:
        """Export all comments with thread embeddings."""
        activity.logger.info(f"Exporting comments for dump {dump_id}")

        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Comment

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Comment)
                .options(joinedload(Comment.author), joinedload(Comment.paper))
            )
            comments = result.scalars().unique().all()

            records = [{
                "id": str(c.id),
                "paper_id": str(c.paper_id),
                "paper_domain": c.paper.domain if c.paper else None,
                "parent_id": str(c.parent_id) if c.parent_id else None,
                "is_root": c.parent_id is None,
                "author_id": str(c.author_id),
                "author_type": c.author.actor_type.value if c.author else None,
                "author_name": c.author.name if c.author else None,
                "content_markdown": c.content_markdown,
                "content_length": len(c.content_markdown),
                "upvotes": c.upvotes,
                "downvotes": c.downvotes,
                "net_score": c.net_score,
                "thread_embedding": list(c.thread_embedding) if c.thread_embedding else None,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            } for c in comments]

        url, count = await _write_and_upload(f"exports/{dump_id}/comments.jsonl", records)
        activity.logger.info(f"Comments dump: {count}")
        return {"file_path": url, "count": count}

    @activity.defn
    async def export_full_events(self, dump_id: str) -> dict:
        """Export all interaction events."""
        activity.logger.info(f"Exporting events for dump {dump_id}")

        from sqlalchemy import select
        from app.db.session import AsyncSessionLocal
        from app.models.platform import InteractionEvent

        async with AsyncSessionLocal() as session:
            offset = 0
            batch_size = 1000
            records = []

            while True:
                result = await session.execute(
                    select(InteractionEvent)
                    .order_by(InteractionEvent.created_at.asc())
                    .offset(offset)
                    .limit(batch_size)
                )
                events = result.scalars().all()
                if not events:
                    break

                records.extend(_event_to_dict(e) for e in events)

                if len(records) % 500 == 0:
                    activity.heartbeat(f"Exported {len(records)} events")

                offset += batch_size

        url, count = await _write_and_upload(f"exports/{dump_id}/events.jsonl", records)
        activity.logger.info(f"Events dump: {count}")
        return {"file_path": url, "count": count}

    @activity.defn
    async def export_full_actors(self, dump_id: str) -> dict:
        """Export all actors with domain authorities."""
        activity.logger.info(f"Exporting actors for dump {dump_id}")

        from sqlalchemy import select
        from app.db.session import AsyncSessionLocal
        from app.models.identity import Actor
        from app.models.platform import DomainAuthority, Domain

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Actor))
            actors = result.scalars().all()

            records = []
            for actor in actors:
                da_result = await session.execute(
                    select(DomainAuthority, Domain.name)
                    .join(Domain, DomainAuthority.domain_id == Domain.id)
                    .where(DomainAuthority.actor_id == actor.id)
                )
                authorities = {
                    name: {
                        "score": da.authority_score,
                        "total_reviews": da.total_reviews,
                        "upvotes": da.total_upvotes_received,
                        "downvotes": da.total_downvotes_received,
                    }
                    for da, name in da_result
                }

                records.append({
                    "id": str(actor.id),
                    "name": actor.name,
                    "actor_type": actor.actor_type.value,
                    "is_active": actor.is_active,
                    "reputation_score": actor.reputation_score,
                    "voting_weight": actor.voting_weight,
                    "domain_authorities": authorities,
                    "created_at": actor.created_at,
                })

        url, count = await _write_and_upload(f"exports/{dump_id}/actors.jsonl", records)
        activity.logger.info(f"Actors dump: {count}")
        return {"file_path": url, "count": count}

    @activity.defn
    async def export_full_votes(self, dump_id: str) -> dict:
        """Export all votes with weights."""
        activity.logger.info(f"Exporting votes for dump {dump_id}")

        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Vote, Paper, Comment

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Vote).options(joinedload(Vote.voter))
            )
            votes = result.scalars().unique().all()

            # Resolve domain for each vote target
            paper_domains = {}
            p_result = await session.execute(select(Paper.id, Paper.domain))
            for pid, domain in p_result:
                paper_domains[str(pid)] = domain

            comment_papers = {}
            c_result = await session.execute(select(Comment.id, Comment.paper_id))
            for cid, pid in c_result:
                comment_papers[str(cid)] = str(pid)

            records = []
            for v in votes:
                target_id_str = str(v.target_id)
                if v.target_type.value == "PAPER":
                    domain = paper_domains.get(target_id_str)
                else:
                    paper_id = comment_papers.get(target_id_str)
                    domain = paper_domains.get(paper_id) if paper_id else None

                records.append({
                    "id": str(v.id),
                    "voter_id": str(v.voter_id),
                    "voter_type": v.voter.actor_type.value if v.voter else None,
                    "target_id": target_id_str,
                    "target_type": v.target_type.value,
                    "vote_value": v.vote_value,
                    "vote_weight": v.vote_weight,
                    "domain": domain,
                    "created_at": v.created_at,
                })

        url, count = await _write_and_upload(f"exports/{dump_id}/votes.jsonl", records)
        activity.logger.info(f"Votes dump: {count}")
        return {"file_path": url, "count": count}

    @activity.defn
    async def export_full_domains(self, dump_id: str) -> dict:
        """Export all domains with stats."""
        activity.logger.info(f"Exporting domains for dump {dump_id}")

        from sqlalchemy import select, func
        from app.db.session import AsyncSessionLocal
        from app.models.platform import Domain, Subscription, Paper

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Domain))
            domains = result.scalars().all()

            records = []
            for d in domains:
                sub_count = (await session.execute(
                    select(func.count()).select_from(Subscription)
                    .where(Subscription.domain_id == d.id)
                )).scalar() or 0

                paper_count = (await session.execute(
                    select(func.count()).select_from(Paper)
                    .where(Paper.domain == d.name)
                )).scalar() or 0

                records.append({
                    "id": str(d.id),
                    "name": d.name,
                    "description": d.description,
                    "subscriber_count": sub_count,
                    "paper_count": paper_count,
                    "created_at": d.created_at,
                })

        url, count = await _write_and_upload(f"exports/{dump_id}/domains.jsonl", records)
        activity.logger.info(f"Domains dump: {count}")
        return {"file_path": url, "count": count}


def _event_to_dict(event) -> dict:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "actor_id": str(event.actor_id),
        "target_id": str(event.target_id) if event.target_id else None,
        "target_type": event.target_type,
        "domain_id": str(event.domain_id) if event.domain_id else None,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


# --- Workflows ---

@workflow.defn
class IncrementalEventExportWorkflow:
    """Runs every 15 minutes. Exports only new events since last run."""

    @workflow.run
    async def run(self) -> IncrementalExportResult:
        result = await workflow.execute_activity_method(
            DataExportActivities.export_incremental_events,
            start_to_close_timeout=timedelta(minutes=5),
        )
        return IncrementalExportResult(
            file_path=result["file_path"],
            events_exported=result["events_exported"],
        )


@workflow.defn
class FullDataDumpWorkflow:
    """On-demand or daily. Exports complete snapshots with embeddings."""

    @workflow.run
    async def run(self) -> FullDumpResult:
        # Use workflow ID as dump folder name for uniqueness
        dump_id = workflow.info().workflow_id

        papers = await workflow.execute_activity_method(
            DataExportActivities.export_full_papers,
            dump_id,
            start_to_close_timeout=timedelta(minutes=10),
        )
        comments = await workflow.execute_activity_method(
            DataExportActivities.export_full_comments,
            dump_id,
            start_to_close_timeout=timedelta(minutes=10),
        )
        events = await workflow.execute_activity_method(
            DataExportActivities.export_full_events,
            dump_id,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
        )
        actors = await workflow.execute_activity_method(
            DataExportActivities.export_full_actors,
            dump_id,
            start_to_close_timeout=timedelta(minutes=10),
        )
        votes = await workflow.execute_activity_method(
            DataExportActivities.export_full_votes,
            dump_id,
            start_to_close_timeout=timedelta(minutes=10),
        )
        domains = await workflow.execute_activity_method(
            DataExportActivities.export_full_domains,
            dump_id,
            start_to_close_timeout=timedelta(minutes=5),
        )

        return FullDumpResult(
            papers_path=papers["file_path"],
            comments_path=comments["file_path"],
            events_path=events["file_path"],
            actors_path=actors["file_path"],
            votes_path=votes["file_path"],
            domains_path=domains["file_path"],
            papers_count=papers["count"],
            comments_count=comments["count"],
            events_count=events["count"],
            actors_count=actors["count"],
            votes_count=votes["count"],
            domains_count=domains["count"],
        )
