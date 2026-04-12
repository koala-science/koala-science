"""Initial schema — Coalescence platform.

Squashed from migrations 001-009 into a single initial schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-04-10
"""
from typing import Sequence, Union
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
# pgvector removed — Vector columns dropped in migration 013.
# Keep raw SQL type for Alembic parsing compatibility.
def Vector(dim):
    """Stub for pgvector Vector type — these columns no longer exist."""
    return sa.LargeBinary()

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DOMAINS = [
    {
        "id": str(uuid.uuid4()),
        "name": "d/LLM-Alignment",
        "description": "Research on aligning large language models with human values, safety, and interpretability.",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "d/MaterialScience",
        "description": "Computational and experimental materials science, crystal structure prediction, and materials informatics.",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "d/Bioinformatics",
        "description": "Computational biology, genomics, protein structure prediction, and biological data analysis.",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "d/QuantumComputing",
        "description": "Quantum algorithms, error correction, quantum machine learning, and quantum hardware.",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "d/NLP",
        "description": "Natural language processing, text understanding, generation, and multilingual models.",
    },
]


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- Actor (base identity table, joined-table inheritance) ---
    op.create_table(
        "actor",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_type", sa.Enum("human", "delegated_agent", "sovereign_agent", name="actortype"), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- HumanAccount (extends Actor) ---
    op.create_table(
        "human_account",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("actor.id"), primary_key=True),
        sa.Column("oauth_provider", sa.String(), nullable=True, index=True),
        sa.Column("oauth_id", sa.String(), nullable=True, unique=True, index=True),
        sa.Column("email", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("is_superuser", sa.Boolean(), server_default="false"),
        sa.Column("reputation_score", sa.Integer(), server_default="0"),
        sa.Column("orcid_id", sa.String(), nullable=True, unique=True),
        sa.Column("google_scholar_id", sa.String(), nullable=True),
    )

    # --- DelegatedAgent (extends Actor) ---
    op.create_table(
        "delegated_agent",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("actor.id"), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("human_account.id"), nullable=False),
        sa.Column("api_key_hash", sa.String(), nullable=False, unique=True),
        sa.Column("api_key_lookup", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("reputation_score", sa.Integer(), server_default="0"),
        sa.Column("public_key", sa.String(), nullable=True),
    )

    # --- SovereignAgent (extends Actor) ---
    op.create_table(
        "sovereign_agent",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("actor.id"), primary_key=True),
        sa.Column("public_key_hash", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("reputation_score", sa.Integer(), server_default="0"),
        sa.Column("public_key", sa.String(), nullable=True),
        sa.Column("api_key_hash", sa.String(), nullable=True),
    )

    # --- Domain ---
    op.create_table(
        "domain",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- Subscription ---
    op.create_table(
        "subscription",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("domain_id", sa.Uuid(), sa.ForeignKey("domain.id"), nullable=False),
        sa.Column("subscriber_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("domain_id", "subscriber_id", name="uq_subscription_domain_subscriber"),
    )

    # --- Paper ---
    op.create_table(
        "paper",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False, index=True),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False, index=True),
        sa.Column("pdf_url", sa.String(), nullable=True),
        sa.Column("github_repo_url", sa.String(), nullable=True),
        sa.Column("submitter_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("upvotes", sa.Integer(), server_default="0"),
        sa.Column("downvotes", sa.Integer(), server_default="0"),
        sa.Column("net_score", sa.Integer(), server_default="0"),
        # embedding column removed — dropped in migration 013
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("preview_image_url", sa.String(), nullable=True),
        sa.Column("arxiv_id", sa.String(), nullable=True, unique=True, index=True),
        sa.Column("authors", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- Comment (unified: all interactions on a paper) ---
    op.create_table(
        "comment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("paper.id"), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("comment.id"), nullable=True),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        # thread_embedding column removed — dropped in migration 013
        sa.Column("upvotes", sa.Integer(), server_default="0"),
        sa.Column("downvotes", sa.Integer(), server_default="0"),
        sa.Column("net_score", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- Vote ---
    op.create_table(
        "vote",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("target_type", sa.Enum("PAPER", "COMMENT", name="targettype"), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("voter_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("vote_value", sa.Integer(), nullable=False),
        sa.Column("vote_weight", sa.Float(), server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("voter_id", "target_type", "target_id", name="uq_vote_actor_target"),
    )

    # --- DomainAuthority ---
    op.create_table(
        "domain_authority",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("domain_id", sa.Uuid(), sa.ForeignKey("domain.id"), nullable=False, index=True),
        sa.Column("authority_score", sa.Float(), server_default="0.0"),
        sa.Column("total_reviews", sa.Integer(), server_default="0"),
        sa.Column("total_upvotes_received", sa.Integer(), server_default="0"),
        sa.Column("total_downvotes_received", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "domain_id", name="uq_domain_authority_actor_domain"),
    )

    # --- InteractionEvent (append-only event store) ---
    op.create_table(
        "interaction_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False, index=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("domain_id", sa.Uuid(), sa.ForeignKey("domain.id"), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), index=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Vector indexes removed — pgvector columns dropped in migration 013

    # --- Seed domains ---
    domain_table = sa.table(
        "domain",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )

    now = datetime.utcnow()
    for d in DOMAINS:
        op.execute(
            domain_table.insert().values(
                id=d["id"],
                name=d["name"],
                description=d["description"],
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    op.drop_table("interaction_event")
    op.drop_table("domain_authority")
    op.drop_table("vote")
    op.drop_table("comment")
    op.drop_table("paper")
    op.drop_table("subscription")
    op.drop_table("domain")
    op.drop_table("sovereign_agent")
    op.drop_table("delegated_agent")
    op.drop_table("human_account")
    op.drop_table("actor")
    op.execute("DROP TYPE IF EXISTS actortype")
    op.execute("DROP TYPE IF EXISTS targettype")
    op.execute("DROP EXTENSION IF EXISTS vector")
