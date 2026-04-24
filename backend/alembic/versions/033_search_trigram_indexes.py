"""Add pg_trgm GIN indexes for hybrid keyword search.

Revision ID: 033_search_trigram_indexes
Revises: 032_paper_github_urls
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = "033_search_trigram_indexes"
down_revision: Union[str, None] = "032_paper_github_urls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index_name, table, column) — column is matched via ILIKE '%q%'
# which trigram GIN serves with gin_trgm_ops.
_TRIGRAM_INDEXES: list[tuple[str, str, str]] = [
    ("ix_paper_title_trgm", "paper", "title"),
    ("ix_paper_abstract_trgm", "paper", "abstract"),
    ("ix_comment_content_trgm", "comment", "content_markdown"),
    ("ix_actor_name_trgm", "actor", "name"),
    ("ix_agent_description_trgm", "agent", "description"),
    ("ix_domain_name_trgm", "domain", "name"),
    ("ix_domain_description_trgm", "domain", "description"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in _TRIGRAM_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} "
            f"ON {table} USING gin ({column} gin_trgm_ops)"
        )


def downgrade() -> None:
    for name, _table, _column in _TRIGRAM_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
