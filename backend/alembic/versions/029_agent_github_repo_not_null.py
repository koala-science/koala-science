"""Require github_repo on every agent.

Revision ID: 029_agent_github_repo_not_null
Revises: 028_wipe_data
Create Date: 2026-04-22

Backfills any existing NULL ``agent.github_repo`` with a placeholder
(``https://github.com/unknown/unknown``) so older records keep a valid
URL, then ALTERs the column to NOT NULL. One-way migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "029_agent_github_repo_not_null"
down_revision: Union[str, None] = "028_wipe_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLACEHOLDER = "https://github.com/unknown/unknown"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agent SET github_repo = :placeholder WHERE github_repo IS NULL"
        ).bindparams(placeholder=PLACEHOLDER)
    )
    op.alter_column("agent", "github_repo", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    raise NotImplementedError("029_agent_github_repo_not_null is a one-way migration")
