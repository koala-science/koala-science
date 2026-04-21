"""Require a unique openreview_id on every human_account.

Revision ID: 018_human_openreview_id
Revises: 017_unify_agents
Create Date: 2026-04-21

Adds a non-nullable, unique ``openreview_id`` column to ``human_account``.
If existing rows are present the upgrade will fail by design — production
data is reset alongside this migration per the hard-break data policy.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "018_human_openreview_id"
down_revision: Union[str, None] = "017_unify_agents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "human_account",
        sa.Column("openreview_id", sa.String(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_human_account_openreview_id", "human_account", ["openreview_id"]
    )
    op.create_index(
        "ix_human_account_openreview_id",
        "human_account",
        ["openreview_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_human_account_openreview_id", table_name="human_account")
    op.drop_constraint(
        "uq_human_account_openreview_id", "human_account", type_="unique"
    )
    op.drop_column("human_account", "openreview_id")
