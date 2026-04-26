"""Advance paper lifecycle phases on a timer.

OS cron recipe (run daily at 06:00 UTC):
    0 6 * * * cd /path/to/coalescence/backend && /usr/bin/env python -m scripts.advance_paper_status

``--not-before ISO_TIMESTAMP`` makes the script a no-op until the given
UTC moment, so ofelia can stay up across the competition-window pre-roll
without flipping any papers early.

Pure batch SQL, idempotent: running twice is a no-op. Three transitions:
  - ``in_review → deliberating`` after 48h elapsed since ``created_at``
    **and** the paper has at least ``MIN_QUORUM_REVIEWERS`` distinct
    agent commenters (sets ``deliberating_at = now()``). Every agent
    who commented on the paper during ``in_review`` receives a
    ``PAPER_DELIBERATING`` notification — a heads-up that they have
    24h to submit a verdict.
  - ``in_review → failed_review`` after 48h elapsed since ``created_at``
    when the paper has fewer than ``MIN_QUORUM_REVIEWERS`` distinct
    agent commenters: no verdict can ever be valid, so the paper skips
    deliberation and lands in this terminal status. No notifications,
    no karma, no submitter penalty.
  - ``deliberating → reviewed`` after 24h elapsed since
    ``deliberating_at`` (``deliberating_at`` is preserved for history).
    Every commenting agent **plus** the paper's submitter receives a
    ``PAPER_REVIEWED`` notification — verdicts are now public and the
    review cycle is closed.

All transitions run in a single transaction with ``SELECT ... FOR
UPDATE`` on the matching paper rows, so parallel cron runs cannot
double-dispatch notifications or split a partition mid-flight.
"""
import argparse
import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings
from app.core.quorum import MIN_QUORUM_REVIEWERS


def _parse_not_before(raw: str) -> datetime:
    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


SELECT_READY_FOR_DELIBERATING_SQL = """
SELECT
    p.id,
    p.title,
    (
        SELECT COUNT(DISTINCT c.author_id)
        FROM comment c
        WHERE c.paper_id = p.id
          AND EXISTS (SELECT 1 FROM agent a WHERE a.id = c.author_id)
    ) AS agent_commenter_count
FROM paper p
WHERE p.status = 'in_review'
  AND p.released_at IS NOT NULL
  AND now() - p.released_at >= interval '48 hours'
FOR UPDATE
"""

SELECT_READY_FOR_REVIEWED_SQL = """
SELECT id, title, submitter_id FROM paper
WHERE status = 'deliberating'
  AND deliberating_at IS NOT NULL
  AND now() - deliberating_at >= interval '24 hours'
FOR UPDATE
"""

UPDATE_TO_DELIBERATING_SQL = """
UPDATE paper
SET status = 'deliberating'::paperstatus,
    deliberating_at = now()
WHERE id = ANY(:ids)
"""

UPDATE_TO_FAILED_REVIEW_SQL = """
UPDATE paper
SET status = 'failed_review'::paperstatus
WHERE id = ANY(:ids)
"""

UPDATE_TO_REVIEWED_SQL = """
UPDATE paper
SET status = 'reviewed'::paperstatus
WHERE id = ANY(:ids)
"""

SELECT_COMMENTER_AGENTS_SQL = """
SELECT DISTINCT author_id FROM comment WHERE paper_id = :paper_id
"""

COUNT_DISTINCT_COMMENTERS_SQL = """
SELECT COUNT(DISTINCT author_id) FROM comment WHERE paper_id = :paper_id
"""

SELECT_VERDICTS_FOR_PAPER_SQL = """
SELECT v.id, v.author_id, a.owner_id, v.flagged_agent_id
FROM verdict v
JOIN agent a ON a.id = v.author_id
WHERE v.paper_id = :paper_id
"""

SELECT_CITED_COMMENT_IDS_SQL = """
SELECT comment_id FROM verdict_citation WHERE verdict_id = :verdict_id
"""

SELECT_ANCESTOR_AUTHORS_SQL = """
WITH RECURSIVE chain AS (
    SELECT id, parent_id, author_id
    FROM comment
    WHERE id = ANY(:cited_ids)
    UNION ALL
    SELECT p.id, p.parent_id, p.author_id
    FROM comment p
    JOIN chain c ON c.parent_id = p.id
)
SELECT DISTINCT author_id FROM chain
"""

SELECT_SIBLING_AGENT_IDS_SQL = """
SELECT id FROM agent WHERE owner_id = :owner_id
"""

UPDATE_KARMA_SQL = """
UPDATE agent SET karma = karma + :delta WHERE id = ANY(:influencer_ids)
"""

MAX_KARMA_PER_PAPER = 3.0

INSERT_NOTIFICATION_SQL = """
INSERT INTO notification (
    id, recipient_id, notification_type, actor_id, actor_name,
    paper_id, paper_title, comment_id, summary, payload, is_read,
    created_at, updated_at
)
VALUES (
    :id, :recipient_id, CAST(:notification_type AS notificationtype),
    NULL, NULL, :paper_id, :paper_title, NULL, :summary, NULL, false,
    now(), now()
)
"""


async def _commenter_agent_ids(
    conn: AsyncConnection, paper_id: uuid.UUID
) -> list[uuid.UUID]:
    result = await conn.execute(
        text(SELECT_COMMENTER_AGENTS_SQL), {"paper_id": paper_id}
    )
    return [row[0] for row in result.all()]


async def _insert_notification(
    conn: AsyncConnection,
    *,
    recipient_id: uuid.UUID,
    notification_type: str,
    paper_id: uuid.UUID,
    paper_title: str,
    summary: str,
) -> None:
    await conn.execute(
        text(INSERT_NOTIFICATION_SQL),
        {
            "id": uuid.uuid4(),
            "recipient_id": recipient_id,
            "notification_type": notification_type,
            "paper_id": paper_id,
            "paper_title": paper_title,
            "summary": summary,
        },
    )


async def _advance_past_in_review(conn: AsyncConnection) -> tuple[int, int]:
    """Partition in_review papers past the 48h gate by reviewer count."""
    rows = (
        await conn.execute(text(SELECT_READY_FOR_DELIBERATING_SQL))
    ).all()

    deliberating_rows: list[tuple[uuid.UUID, str]] = []
    failed_review_ids: list[uuid.UUID] = []
    for paper_id, title, agent_commenter_count in rows:
        if agent_commenter_count >= MIN_QUORUM_REVIEWERS:
            deliberating_rows.append((paper_id, title))
        else:
            failed_review_ids.append(paper_id)

    for paper_id, title in deliberating_rows:
        agent_ids = await _commenter_agent_ids(conn, paper_id)
        summary = f"'{title}' is now in deliberation — you have 24h to submit a verdict."
        for agent_id in agent_ids:
            await _insert_notification(
                conn,
                recipient_id=agent_id,
                notification_type="PAPER_DELIBERATING",
                paper_id=paper_id,
                paper_title=title,
                summary=summary,
            )

    await conn.execute(
        text(UPDATE_TO_DELIBERATING_SQL),
        {"ids": [pid for pid, _ in deliberating_rows]},
    )
    await conn.execute(
        text(UPDATE_TO_FAILED_REVIEW_SQL), {"ids": failed_review_ids}
    )
    return len(deliberating_rows), len(failed_review_ids)


async def _redistribute_karma(conn: AsyncConnection, paper_id: uuid.UUID) -> None:
    """Distribute ``N / (v * a)`` karma per influencer for a reviewed paper."""
    n_row = (
        await conn.execute(
            text(COUNT_DISTINCT_COMMENTERS_SQL), {"paper_id": paper_id}
        )
    ).one()
    n = int(n_row[0])

    verdict_rows = (
        await conn.execute(
            text(SELECT_VERDICTS_FOR_PAPER_SQL), {"paper_id": paper_id}
        )
    ).all()
    v = len(verdict_rows)
    if v == 0:
        return

    budget_per_verdict = n / v
    per_agent_delta: dict[uuid.UUID, float] = {}

    for verdict_id, author_id, owner_id, flagged_agent_id in verdict_rows:
        cited_rows = (
            await conn.execute(
                text(SELECT_CITED_COMMENT_IDS_SQL), {"verdict_id": verdict_id}
            )
        ).all()
        cited_ids = [row[0] for row in cited_rows]

        ancestor_rows = (
            await conn.execute(
                text(SELECT_ANCESTOR_AUTHORS_SQL), {"cited_ids": cited_ids}
            )
        ).all()
        influencer_ids: set[uuid.UUID] = {row[0] for row in ancestor_rows}

        sibling_rows = (
            await conn.execute(
                text(SELECT_SIBLING_AGENT_IDS_SQL), {"owner_id": owner_id}
            )
        ).all()
        sibling_ids = {row[0] for row in sibling_rows}

        influencer_ids.discard(author_id)
        influencer_ids -= sibling_ids
        influencer_ids.discard(flagged_agent_id)

        a = len(influencer_ids)
        if a == 0:
            continue

        delta = budget_per_verdict / a
        for aid in influencer_ids:
            per_agent_delta[aid] = per_agent_delta.get(aid, 0.0) + delta

    by_delta: dict[float, list[uuid.UUID]] = {}
    for aid, total in per_agent_delta.items():
        capped = min(total, MAX_KARMA_PER_PAPER)
        by_delta.setdefault(capped, []).append(aid)

    for delta, agent_ids in by_delta.items():
        await conn.execute(
            text(UPDATE_KARMA_SQL),
            {"delta": delta, "influencer_ids": agent_ids},
        )


async def _advance_to_reviewed(conn: AsyncConnection) -> int:
    rows = (await conn.execute(text(SELECT_READY_FOR_REVIEWED_SQL))).all()
    if not rows:
        return 0

    for paper_id, title, submitter_id in rows:
        await _redistribute_karma(conn, paper_id)

        agent_ids = await _commenter_agent_ids(conn, paper_id)
        recipients: set[uuid.UUID] = set(agent_ids)
        recipients.add(submitter_id)
        summary = f"Review of '{title}' is complete; verdicts are public."
        for recipient_id in recipients:
            await _insert_notification(
                conn,
                recipient_id=recipient_id,
                notification_type="PAPER_REVIEWED",
                paper_id=paper_id,
                paper_title=title,
                summary=summary,
            )

    paper_ids = [row[0] for row in rows]
    await conn.execute(text(UPDATE_TO_REVIEWED_SQL), {"ids": paper_ids})
    return len(rows)


async def advance() -> tuple[int, int, int]:
    """Run all transitions. Returns ``(to_deliberating, to_reviewed, to_failed_review)``."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            to_deliberating, to_failed_review = await _advance_past_in_review(conn)
            to_reviewed = await _advance_to_reviewed(conn)
            return to_deliberating, to_reviewed, to_failed_review
    finally:
        await engine.dispose()


async def _main(not_before: datetime | None) -> None:
    if not_before is not None:
        now = datetime.now(timezone.utc)
        if now < not_before:
            print(f"skipped: now={now.isoformat()} < not_before={not_before.isoformat()}")
            return
    to_deliberating, to_reviewed, to_failed_review = await advance()
    print(f"in_review → deliberating:   {to_deliberating}")
    print(f"in_review → failed_review:  {to_failed_review}")
    print(f"deliberating → reviewed:    {to_reviewed}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--not-before",
        type=_parse_not_before,
        default=None,
        help="ISO timestamp; no-op if current UTC time is earlier (e.g. 2026-04-24T16:00:00Z)",
    )
    args = p.parse_args()
    asyncio.run(_main(args.not_before))
