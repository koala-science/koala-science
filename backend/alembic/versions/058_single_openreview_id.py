"""One OpenReview ID per human, back on the account itself.

A human may now hold at most one OpenReview ID, so the child table that held up
to three is exactly a column again. Collapsing it removes the cap trigger
installed in 030 and the advisory lock 038 added to close its TOCTOU race — a
column can hold one value by construction, with nothing left to serialise.

Nullable rather than NOT NULL: signup requires an ID and every script that
creates an account supplies one, but databases built by metadata.create_all
rather than by this chain already hold accounts with none — the local dev
database has four — and nothing valid can be invented for them. Postgres permits
repeated NULLs under a unique index, so "at most one, globally unique" is
expressed exactly.

Humans holding several IDs keep one and lose the rest. Which one is arbitrary
where they were claimed together: signup inserted them in a single statement, so
they share a created_at and the tie-break falls to a random uuid. Nothing records
which the user considered primary, so there is nothing better to order by.

Revision ID: 058_single_openreview_id
Revises: 057_points_per_user
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "058_single_openreview_id"
down_revision: Union[str, None] = "057_points_per_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The cap this migration removes, restored by downgrade. Matches 030 and 038.
MAX_IDS_PER_HUMAN = 3


def upgrade() -> None:
    op.add_column(
        "human_account", sa.Column("openreview_id", sa.String(), nullable=True)
    )
    op.execute(
        """
        UPDATE human_account
        SET openreview_id = earliest.value
        FROM (
            SELECT DISTINCT ON (human_account_id) human_account_id, value
            FROM openreview_id
            ORDER BY human_account_id, created_at, id
        ) AS earliest
        WHERE human_account.id = earliest.human_account_id
        """
    )
    op.create_unique_constraint(
        "uq_human_account_openreview_id", "human_account", ["openreview_id"]
    )

    op.execute("DROP TRIGGER IF EXISTS openreview_id_cap_trigger ON openreview_id")
    op.execute("DROP FUNCTION IF EXISTS enforce_openreview_id_cap()")
    op.drop_table("openreview_id")


def downgrade() -> None:
    op.create_table(
        "openreview_id",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("human_account_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["human_account_id"], ["human_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("value"),
    )
    op.create_index(
        "ix_openreview_id_human_account_id", "openreview_id", ["human_account_id"]
    )
    op.execute(
        """
        INSERT INTO openreview_id (id, human_account_id, value)
        SELECT gen_random_uuid(), id, openreview_id
        FROM human_account
        WHERE openreview_id IS NOT NULL
        """
    )
    # 038's downgrade only replaces the function body and 030's raises, so
    # neither restores what this migration dropped. Without recreating both here,
    # revisions 054-057 would have the table back and nothing capping it.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION enforce_openreview_id_cap()
        RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtext('openreview_id_cap'),
                hashtext(NEW.human_account_id::text)
            );
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
    op.execute(
        "CREATE TRIGGER openreview_id_cap_trigger "
        "BEFORE INSERT ON openreview_id "
        "FOR EACH ROW EXECUTE FUNCTION enforce_openreview_id_cap()"
    )

    op.drop_constraint("uq_human_account_openreview_id", "human_account", type_="unique")
    op.drop_column("human_account", "openreview_id")
