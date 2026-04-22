"""One-shot wipe of all user data to restart the platform from scratch.

Revision ID: 028_wipe_data
Revises: 027_agent_strikes
Create Date: 2026-04-22

TRUNCATEs every user-data table with CASCADE + RESTART IDENTITY, leaving
the schema intact and the alembic version table untouched. Runs once as
part of the ``feat/new-incentives`` deploy; fresh databases no-op
(TRUNCATE on an empty table is a no-op). One-way migration.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "028_wipe_data"
down_revision: Union[str, None] = "027_agent_strikes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    "actor",
    "agent",
    "human_account",
    "domain",
    "subscription",
    "paper",
    "comment",
    "verdict",
    "verdict_citation",
    "interaction_event",
    "notification",
]


def upgrade() -> None:
    op.execute(
        "TRUNCATE TABLE "
        + ", ".join(TABLES)
        + " RESTART IDENTITY CASCADE"
    )


def downgrade() -> None:
    raise NotImplementedError("028_wipe_data is a one-way migration")
