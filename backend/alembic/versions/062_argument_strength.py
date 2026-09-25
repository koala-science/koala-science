"""An accepted argument's strength: weak, medium or critical.

Set by the verification agent after it verifies an argument, by resuming its own
session, so the label draws on what it read while verifying. Arguments accepted
before this existed have no such session to resume; they are labelled weak, with
no reason.

Revision ID: 062_argument_strength
Revises: 061_paper_author_response
"""
import sqlalchemy as sa
from alembic import op

revision = "062_argument_strength"
down_revision = "061_paper_author_response"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # add_column does not create the type the way create_table does.
    argument_strength = sa.Enum("weak", "medium", "critical", name="argumentstrength")
    argument_strength.create(op.get_bind(), checkfirst=True)
    op.add_column("argument", sa.Column("strength", argument_strength, nullable=True))
    op.add_column("argument", sa.Column("strength_reason", sa.Text(), nullable=True))
    op.execute("UPDATE argument SET strength = 'weak' WHERE state = 'accepted'")


def downgrade() -> None:
    op.drop_column("argument", "strength_reason")
    op.drop_column("argument", "strength")
    sa.Enum(name="argumentstrength").drop(op.get_bind(), checkfirst=True)
