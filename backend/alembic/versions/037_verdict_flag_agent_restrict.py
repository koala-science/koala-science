"""Verdict.flagged_agent_id FK gains ON DELETE RESTRICT.

Revision ID: 037_verdict_flag_agent_restrict
Revises: 034_paper_released_at
Create Date: 2026-04-24

The ``flagged_agent_id`` FK had no ondelete policy. Deleting a flagged
agent would cascade unpredictably and could orphan the ``flag_reason``
text (or violate the ``both_or_neither`` CHECK constraint, which
requires ``(flagged_agent_id IS NULL) = (flag_reason IS NULL)``).

RESTRICT forces admins to clear ``flag_reason`` (and the flag) before
deleting a flagged agent, preserving verdict flag history.

Pure FK-behavior change; no data is touched.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "037_verdict_flag_agent_restrict"
down_revision: Union[str, None] = "034_paper_released_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("verdict_flagged_agent_id_fkey", "verdict", type_="foreignkey")
    op.create_foreign_key(
        "verdict_flagged_agent_id_fkey",
        "verdict",
        "agent",
        ["flagged_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("verdict_flagged_agent_id_fkey", "verdict", type_="foreignkey")
    op.create_foreign_key(
        "verdict_flagged_agent_id_fkey",
        "verdict",
        "agent",
        ["flagged_agent_id"],
        ["id"],
    )
