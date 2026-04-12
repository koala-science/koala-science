"""Add description column to delegated_agent

Revision ID: 010_agent_description
Revises: 009_notifications
"""
from alembic import op
import sqlalchemy as sa

revision = "010_agent_description"
down_revision = "009_notifications"


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    insp = sa_inspect(bind)
    columns = [c["name"] for c in insp.get_columns("delegated_agent")]
    if "description" not in columns:
        op.add_column("delegated_agent", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("delegated_agent", "description")
