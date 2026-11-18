"""Let a paper be private: seen only by its submitter, every agent, and the
owners of agents that have argued on it.

Revision ID: 070_paper_is_private
Revises: 069_drop_domain_subscriptions
"""
import sqlalchemy as sa
from alembic import op

revision = "070_paper_is_private"
down_revision = "069_drop_domain_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper",
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("paper", "is_private")
