"""Add arguments and their check results.

Creates the two tables the argument model needs. Removal of ``comment``,
``verdict`` and the annotation tables lands in a separate migration, so this
one is additive and safe to run anywhere.

``argument_check`` is unique on (argument, name, version): bumping a checker's
version writes a new row alongside the old rather than overwriting it, so two
versions can be compared over the same corpus.

Revision ID: 053_arguments
Revises: 052_polarity_neutral_choice
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "053_arguments"
down_revision: Union[str, None] = "052_polarity_neutral_choice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "argument",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column(
            "position",
            sa.Enum("positive", "negative", name="argumentposition"),
            nullable=False,
        ),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["actor.id"]),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_argument_paper_id", "argument", ["paper_id"])
    op.create_index("ix_argument_author_id", "argument", ["author_id"])

    op.create_table(
        "argument_check",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("argument_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "passed", "failed", name="checkstatus"),
            nullable=False,
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["argument_id"], ["argument.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "argument_id", "name", "version", name="uq_argument_check_version"
        ),
    )
    op.create_index("ix_argument_check_argument_id", "argument_check", ["argument_id"])


def downgrade() -> None:
    op.drop_table("argument_check")
    op.drop_table("argument")
    sa.Enum(name="checkstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="argumentposition").drop(op.get_bind(), checkfirst=True)
