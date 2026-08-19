"""Drop comments, verdicts, karma, the annotation subsystem, and the paper lifecycle.

Arguments replace all of it. Destructive by design and safe here: v1 runs on an
empty database, and the v0 archive is a separate database on the same instance,
untouched.

``released_at`` survives — that is the pre-release embargo the ingest scripts
rely on, not lifecycle. Only ``status`` and ``deliberating_at`` go.

Revision ID: 054_drop_comments_verdicts
Revises: 053_arguments
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "054_drop_comments_verdicts"
down_revision: Union[str, None] = "053_arguments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Children before parents.
_TABLES = [
    "annotation_response",
    "annotation_page_state",
    "annotation_assignment",
    "annotation_batch_fact",
    "annotation_batch_agent_paper",
    "annotation_batch_paper",
    "annotation_batch_agent",
    "annotation_question",
    "annotation_batch",
    "comment_fact",
    "comment_fact_extraction_run",
    "moderation_event",
    "verdict_citation",
    "verdict",
    "comment",
]

_ENUMS = ["annotationlevel", "annotationresponsetype", "paperstatus"]


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    op.drop_column("paper", "status")
    op.drop_column("paper", "deliberating_at")
    op.drop_column("agent", "karma")
    op.drop_column("agent", "strike_count")

    for enum in _ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {enum}")

    # Only PAPER_IN_DOMAIN survives. Postgres cannot drop a value from an enum,
    # so the type is recreated; otherwise it keeps four values the model can no
    # longer read back, which a non-ORM insert could still write.
    #
    # The delete has to come first: notifications of the retired types are the
    # ones carrying comment ids, and dropping the comment table with CASCADE
    # removed the foreign key but left those ids behind. Adding the new key to
    # `argument` before clearing them fails validation on any non-empty table.
    op.execute("DELETE FROM notification WHERE notification_type::text != 'PAPER_IN_DOMAIN'")

    op.execute("ALTER TYPE notificationtype RENAME TO notificationtype_old")
    op.execute("CREATE TYPE notificationtype AS ENUM ('PAPER_IN_DOMAIN')")
    op.execute(
        "ALTER TABLE notification ALTER COLUMN notification_type "
        "TYPE notificationtype USING notification_type::text::notificationtype"
    )
    op.execute("DROP TYPE notificationtype_old")

    op.alter_column("notification", "comment_id", new_column_name="argument_id")
    op.create_foreign_key(
        "notification_argument_id_fkey", "notification", "argument",
        ["argument_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Irreversible: the dropped tables held the v0 discussion model. "
        "Restore from the v0 archive database instead."
    )
