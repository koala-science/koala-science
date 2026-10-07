"""Rename the points balance to budget, and restart every account at 50.

The economy is unchanged — an argument costs 1 and an accepted one pays 2 — but
every account, existing ones included, starts over at the new default. That
reset is not reversible: the downgrade restores the name and the old default of
100, not the balances this overwrote.

Revision ID: 064_budget
Revises: 063_strength_flag
"""
from alembic import op

revision = "064_budget"
down_revision = "063_strength_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("human_account", "points", new_column_name="budget", server_default="50")
    op.execute(
        "ALTER TABLE human_account RENAME CONSTRAINT human_account_points_non_negative "
        "TO human_account_budget_non_negative"
    )
    op.execute("UPDATE human_account SET budget = 50")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE human_account RENAME CONSTRAINT human_account_budget_non_negative "
        "TO human_account_points_non_negative"
    )
    op.alter_column("human_account", "budget", new_column_name="points", server_default="100")
