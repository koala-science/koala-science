"""Normalize OpenReview IDs into their own table.

Revision ID: 030_openreview_ids_table
Revises: 029_agent_github_repo_not_null
Create Date: 2026-04-23

Creates the ``openreview_id`` table, backfills from
``human_account.openreview_id``, installs a trigger that caps each human
at 3 IDs, and drops the old ``human_account.openreview_id`` column.
One-way migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "030_openreview_ids_table"
down_revision: Union[str, None] = "029_agent_github_repo_not_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MAX_IDS_PER_HUMAN = 3


def upgrade() -> None:
    op.create_table(
        "openreview_id",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "human_account_id",
            sa.Uuid(),
            sa.ForeignKey("human_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("value", name="uq_openreview_id_value"),
    )
    op.create_index(
        "ix_openreview_id_human_account_id",
        "openreview_id",
        ["human_account_id"],
    )

    op.execute(
        sa.text(
            "INSERT INTO openreview_id (id, human_account_id, value, created_at, updated_at) "
            "SELECT gen_random_uuid(), id, openreview_id, now(), now() "
            "FROM human_account WHERE openreview_id IS NOT NULL"
        )
    )

    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION enforce_openreview_id_cap()
            RETURNS TRIGGER AS $$
            BEGIN
                IF (
                    SELECT COUNT(*) FROM openreview_id
                    WHERE human_account_id = NEW.human_account_id
                ) >= {MAX_IDS_PER_HUMAN} THEN
                    RAISE EXCEPTION 'a human may have at most {MAX_IDS_PER_HUMAN} OpenReview IDs';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER openreview_id_cap_trigger "
            "BEFORE INSERT ON openreview_id "
            "FOR EACH ROW EXECUTE FUNCTION enforce_openreview_id_cap();"
        )
    )

    op.drop_index("ix_human_account_openreview_id", table_name="human_account")
    op.drop_constraint(
        "uq_human_account_openreview_id", "human_account", type_="unique"
    )
    op.drop_column("human_account", "openreview_id")


def downgrade() -> None:
    raise NotImplementedError("030_openreview_ids_table is a one-way migration")
