"""A check flag can dispute an argument's strength label instead of a check.

A strength flag targets the argument rather than its verification row: the
arguments labelled weak by 062 were accepted before verification existed and
have no such row. It records the level it disputes, so an admin reading the
flag sees what the reader saw. Exactly one target per flag.

Revision ID: 063_strength_flag
Revises: 062_argument_strength
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "063_strength_flag"
down_revision = "062_argument_strength"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("check_flag", "check_id", nullable=True)
    op.add_column("check_flag", sa.Column("argument_id", sa.Uuid(), nullable=True))
    op.add_column(
        "check_flag",
        sa.Column(
            "strength",
            postgresql.ENUM(name="argumentstrength", create_type=False),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "check_flag_argument_id_fkey", "check_flag", "argument",
        ["argument_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_check_flag_argument_id", "check_flag", ["argument_id"])
    op.create_unique_constraint(
        "uq_strength_flag_one_per_actor", "check_flag", ["argument_id", "flagger_id"]
    )
    op.create_check_constraint(
        "check_flag_one_target",
        "check_flag",
        "(check_id IS NOT NULL AND argument_id IS NULL AND strength IS NULL)"
        " OR (check_id IS NULL AND argument_id IS NOT NULL AND strength IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM check_flag WHERE check_id IS NULL")
    op.drop_constraint("check_flag_one_target", "check_flag", type_="check")
    op.drop_constraint("uq_strength_flag_one_per_actor", "check_flag", type_="unique")
    op.drop_index("ix_check_flag_argument_id", table_name="check_flag")
    op.drop_constraint("check_flag_argument_id_fkey", "check_flag", type_="foreignkey")
    op.drop_column("check_flag", "strength")
    op.drop_column("check_flag", "argument_id")
    op.alter_column("check_flag", "check_id", nullable=False)
