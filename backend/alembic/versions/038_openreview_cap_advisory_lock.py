"""Serialize openreview_id cap trigger via advisory lock.

Revision ID: 038_openreview_cap_advisory_lock
Revises: 037_verdict_flag_agent_restrict
Create Date: 2026-04-23

The ``enforce_openreview_id_cap`` trigger installed in migration 030 reads
``COUNT(*)`` and raises if it is already at the cap. Under ``READ COMMITTED``
two concurrent inserts for the same ``human_account_id`` can both observe
``count < cap`` and both commit, exceeding the cap (TOCTOU).

This migration replaces the function with a version that acquires a
transactional advisory lock keyed on ``human_account_id`` before the count
check, serializing concurrent inserts for the same human. ``pg_advisory_xact_lock``
auto-releases at commit/rollback; ``hashtext`` produces the ``int4`` key.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "038_openreview_cap_advisory_lock"
down_revision: Union[str, None] = "037_verdict_flag_agent_restrict"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MAX_IDS_PER_HUMAN = 3


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION enforce_openreview_id_cap()
            RETURNS TRIGGER AS $$
            BEGIN
                -- Serialize concurrent inserts for the same human so the
                -- count check below cannot race with a sibling transaction.
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
    )


def downgrade() -> None:
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
