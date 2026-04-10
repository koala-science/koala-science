"""Add paper revisions.

Revision ID: 002_paper_revisions
Revises: 001_initial
Create Date: 2026-04-10
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "002_paper_revisions"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_revision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("paper.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("pdf_url", sa.String(), nullable=True),
        sa.Column("github_repo_url", sa.String(), nullable=True),
        sa.Column("preview_image_url", sa.String(), nullable=True),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("paper_id", "version", name="uq_paper_revision_paper_version"),
    )
    op.create_index(op.f("ix_paper_revision_paper_id"), "paper_revision", ["paper_id"], unique=False)
    op.create_index(op.f("ix_paper_revision_created_by_id"), "paper_revision", ["created_by_id"], unique=False)
    op.create_index(op.f("ix_paper_revision_title"), "paper_revision", ["title"], unique=False)

    bind = op.get_bind()
    paper_rows = bind.execute(
        sa.text(
            """
            SELECT id, submitter_id, title, abstract, pdf_url, github_repo_url, preview_image_url, created_at, updated_at
            FROM paper
            """
        )
    ).mappings()

    for row in paper_rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO paper_revision (
                    id,
                    paper_id,
                    version,
                    created_by_id,
                    title,
                    abstract,
                    pdf_url,
                    github_repo_url,
                    preview_image_url,
                    changelog,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :paper_id,
                    1,
                    :created_by_id,
                    :title,
                    :abstract,
                    :pdf_url,
                    :github_repo_url,
                    :preview_image_url,
                    NULL,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "paper_id": row["id"],
                "created_by_id": row["submitter_id"],
                "title": row["title"],
                "abstract": row["abstract"],
                "pdf_url": row["pdf_url"],
                "github_repo_url": row["github_repo_url"],
                "preview_image_url": row["preview_image_url"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_paper_revision_title"), table_name="paper_revision")
    op.drop_index(op.f("ix_paper_revision_created_by_id"), table_name="paper_revision")
    op.drop_index(op.f("ix_paper_revision_paper_id"), table_name="paper_revision")
    op.drop_table("paper_revision")
