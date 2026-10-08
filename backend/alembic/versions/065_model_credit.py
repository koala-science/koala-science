"""Model credit for agents' Gemini calls through the LLM proxy, and its ledger.

Every human account, existing ones included, gets the one-off $10 grant: the
server default fills the new column for every row.

Revision ID: 065_model_credit
Revises: 064_budget
"""
import sqlalchemy as sa
from alembic import op

revision = "065_model_credit"
down_revision = "064_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "human_account",
        sa.Column("model_credit_microusd", sa.BigInteger(), nullable=False, server_default="10000000"),
    )
    op.create_check_constraint(
        "human_account_model_credit_non_negative", "human_account", "model_credit_microusd >= 0"
    )
    op.create_table(
        "model_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reserved_microusd", sa.BigInteger(), nullable=False),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("upstream_status", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["human_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_usage_owner_id", "model_usage", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_model_usage_owner_id", table_name="model_usage")
    op.drop_table("model_usage")
    op.drop_constraint("human_account_model_credit_non_negative", "human_account", type_="check")
    op.drop_column("human_account", "model_credit_microusd")
