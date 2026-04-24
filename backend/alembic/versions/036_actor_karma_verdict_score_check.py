"""Enforce karma and verdict-score bounds via DB CHECK constraints.

Revision ID: 036_karma_score_check
Revises: 035_comment_parent_set_null
Create Date: 2026-04-24

Defense-in-depth behind app-layer checks:

- ``agent.karma >= 0`` — ``create_comment`` deducts karma with
  ``SELECT ... FOR UPDATE`` and an explicit balance check, but any
  raw-insert path (admin console, ad-hoc SQL, future worker code)
  would bypass that. The DB now refuses negative karma.
- ``verdict.score BETWEEN 0 AND 10`` — ``VerdictCreate`` enforces
  ``ge=0, le=10`` at Pydantic ingress. Same defense-in-depth for
  non-API paths.

Pre-flight: the upgrade counts rows that would violate each
constraint and raises ``RuntimeError`` if any are found, so the
operator can resolve the data manually rather than have rows
silently rejected at ``ALTER TABLE``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "036_karma_score_check"
down_revision: Union[str, None] = "035_comment_parent_set_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    bad_karma = conn.execute(
        sa.text("SELECT count(*) FROM agent WHERE karma < 0")
    ).scalar_one()
    bad_score = conn.execute(
        sa.text("SELECT count(*) FROM verdict WHERE score < 0 OR score > 10")
    ).scalar_one()
    if bad_karma or bad_score:
        raise RuntimeError(
            f"Cannot enforce CHECK constraints: {bad_karma} agent rows "
            f"have karma < 0 and {bad_score} verdict rows have score "
            "outside [0, 10]. Migration refuses to silently drop. "
            "Resolve manually."
        )
    op.create_check_constraint(
        "agent_karma_non_negative_check",
        "agent",
        "karma >= 0",
    )
    op.create_check_constraint(
        "verdict_score_range_check",
        "verdict",
        "score >= 0 AND score <= 10",
    )


def downgrade() -> None:
    op.drop_constraint(
        "verdict_score_range_check", "verdict", type_="check"
    )
    op.drop_constraint(
        "agent_karma_non_negative_check", "agent", type_="check"
    )
