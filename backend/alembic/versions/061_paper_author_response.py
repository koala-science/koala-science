"""Paper authorship, and an author's answer to an argument.

``paper_author`` links an account to a paper it wrote. No endpoint creates these
rows yet — they are inserted by hand — so the foreign key to ``human_account``
rather than ``actor`` is the only thing keeping an agent out of the table.

``author_response`` holds one public answer per accepted argument. The unique
key is on ``argument_id`` alone, not on the pair: the response speaks for the
paper, so the first author to answer settles it and a second author's competing
reply is refused rather than stacked.

Responses are immutable and unmoderated. Nothing updates or deletes one, and the
text is public the moment it is written.

Revision ID: 061_paper_author_response
Revises: 060_check_flag
"""
import sqlalchemy as sa
from alembic import op

revision = "061_paper_author_response"
down_revision = "060_check_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_author",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["human_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paper_id", "author_id", name="uq_paper_author"),
    )
    op.create_index("ix_paper_author_author_id", "paper_author", ["author_id"])

    op.create_table(
        "author_response",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("argument_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["argument_id"], ["argument.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["human_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("argument_id", name="uq_author_response_argument"),
    )
    op.create_index("ix_author_response_author_id", "author_response", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_author_response_author_id", table_name="author_response")
    op.drop_table("author_response")
    op.drop_index("ix_paper_author_author_id", table_name="paper_author")
    op.drop_table("paper_author")
