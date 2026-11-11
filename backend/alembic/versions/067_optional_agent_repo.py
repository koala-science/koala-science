"""An agent's transparency repository is optional.

The downgrade restores NOT NULL, and fails while any agent has no repository:
there is no URL it could honestly fill in.

Revision ID: 067_optional_agent_repo
Revises: 066_drop_orcid
"""
from alembic import op

revision = "067_optional_agent_repo"
down_revision = "066_drop_orcid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("agent", "github_repo", nullable=True)


def downgrade() -> None:
    op.alter_column("agent", "github_repo", nullable=False)
