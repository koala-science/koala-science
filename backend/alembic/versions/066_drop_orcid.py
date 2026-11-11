"""Drop ORCID: the linking flow is gone, and so is the iD it stored.

The downgrade restores the column, not the iDs: they are deleted by the upgrade.

Revision ID: 066_drop_orcid
Revises: 065_model_credit
"""
import sqlalchemy as sa
from alembic import op

revision = "066_drop_orcid"
down_revision = "065_model_credit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("human_account", "orcid_id")


def downgrade() -> None:
    op.add_column("human_account", sa.Column("orcid_id", sa.String(), nullable=True))
    op.create_unique_constraint("human_account_orcid_id_key", "human_account", ["orcid_id"])
