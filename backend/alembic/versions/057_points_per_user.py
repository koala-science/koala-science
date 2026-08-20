"""Move the points balance from the agent to its owner.

A human's agents now draw on and refill one shared pool, so the balance belongs
on ``human_account``. Nothing else about the economy changes: same default, same
non-negative constraint, same cost and reward.

Balances carry over as net earnings: the sum of the owner's agents, less the 100
each agent beyond the first was granted at signup. A plain sum would hand a human
with three untouched agents 300 against the 100 a new account opens with, minting
points the economy never paid out. GREATEST clamps at zero because three drained
agents would otherwise backfill negative and trip the new check constraint
mid-migration. Production has no accounts yet, so there this is a no-op.

Revision ID: 057_points_per_user
Revises: 056_argument_embedding
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "057_points_per_user"
down_revision: Union[str, None] = "056_argument_embedding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "human_account",
        sa.Column("points", sa.Integer(), nullable=False, server_default="100"),
    )
    op.create_check_constraint(
        "human_account_points_non_negative", "human_account", "points >= 0"
    )
    op.execute(
        """
        UPDATE human_account
        SET points = agent_total.total
        FROM (
            SELECT owner_id,
                   GREATEST(SUM(points) - 100 * (COUNT(*) - 1), 0) AS total
            FROM agent
            GROUP BY owner_id
        ) AS agent_total
        WHERE human_account.id = agent_total.owner_id
        """
    )

    op.drop_column("agent", "points")


def downgrade() -> None:
    # The pool cannot be split back across agents, so every agent returns to the
    # default rather than to a share of it.
    op.add_column(
        "agent",
        sa.Column("points", sa.Integer(), nullable=False, server_default="100"),
    )
    op.create_check_constraint("agent_points_non_negative", "agent", "points >= 0")
    op.drop_column("human_account", "points")
