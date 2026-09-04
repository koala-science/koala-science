"""Flagging a check result as wrong.

The target is a check row rather than a check name. A name carries a result per
checker version, and a dispute is about the verdict that was actually reached,
so pinning the row keeps a flag attached to the thing it contests even after the
check is re-run at a newer version.

One flag per actor per row, enforced in the schema: a second opinion from the
same person is an edit of the first, and the endpoint asks them to withdraw and
re-file rather than accumulating rows nobody can weigh.

Reasons are not public. Nothing in this table is served by the paper page —
only the count is — so the column carries no visibility flag of its own.

``check_id`` needs no index of its own: it leads the unique constraint's btree,
which serves every lookup by check.

Revision ID: 060_check_flag
Revises: 059_email_verification
"""
import sqlalchemy as sa
from alembic import op

revision = "060_check_flag"
down_revision = "059_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "check_flag",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("check_id", sa.Uuid(), nullable=False),
        sa.Column("flagger_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["check_id"], ["argument_check.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["flagger_id"], ["actor.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("check_id", "flagger_id", name="uq_check_flag_one_per_actor"),
    )
    op.create_index("ix_check_flag_flagger_id", "check_flag", ["flagger_id"])


def downgrade() -> None:
    op.drop_index("ix_check_flag_flagger_id", table_name="check_flag")
    op.drop_table("check_flag")
