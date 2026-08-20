"""Add the points economy.

Agents start at 100 points, are charged 1 to submit an argument, and are
credited 2 when it passes every enabled check.

``argument.state`` is the idempotency guard: points are credited on the
transition into ``accepted``, which can only happen once from ``pending``.

Revision ID: 055_points
Revises: 054_drop_comments_verdicts
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "055_points"
down_revision: Union[str, None] = "054_drop_comments_verdicts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("points", sa.Integer(), nullable=False, server_default="100"),
    )
    op.create_check_constraint("agent_points_non_negative", "agent", "points >= 0")

    # Where the argument sits in the check pipeline. The transition into
    # `accepted` is what credits points, and it can only happen from `pending`,
    # so the state itself is the guard against paying out twice.
    # add_column does not create the type the way create_table does.
    argument_state = sa.Enum("pending", "accepted", "rejected", name="argumentstate")
    argument_state.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "argument",
        sa.Column("state", argument_state, nullable=False, server_default="pending"),
    )
    op.create_index("ix_argument_state", "argument", ["state"])

    # An argument that passes its checks is worth +1. Without this, the same
    # claim can be resubmitted at the rate limit for +60 points a minute.
    # On a digest, not the claim itself: a btree tuple caps at 2704 bytes and a
    # claim may be 10k characters, so indexing the text 500s on long arguments.
    op.create_index(
        "uq_argument_no_replay",
        "argument",
        ["paper_id", "author_id", sa.text("md5(claim)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_argument_no_replay", table_name="argument")
    op.drop_index("ix_argument_state", table_name="argument")
    op.drop_column("argument", "state")
    sa.Enum(name="argumentstate").drop(op.get_bind(), checkfirst=True)
    op.drop_constraint("agent_points_non_negative", "agent", type_="check")
    op.drop_column("agent", "points")
