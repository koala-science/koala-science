"""Email verification, and the OpenReview name behind the claim.

An account's `email` is the whole basis for believing its `openreview_id`: the
address must sit at a domain the claimed profile lists, and be proven by a link.
Until that link is clicked the account cannot log in, so `email_verified` starts
false and no backfill is needed — production has no users.

`openreview_name` records who OpenReview said the ID belonged to at signup, so a
later divergence between the name someone uses here and the profile they claimed
is visible rather than lost.

Only the SHA-256 of each token is stored. The raw value exists in the email and
nowhere else, so reading `email_verification_token` yields nothing usable.

Each token carries the OpenReview claim it stands for, and no credentials.
Anyone can post a signup for any address, so a password travelling in the link
would be a password chosen by whoever posted it and installed by whoever holds
the mailbox — a stranger could have the real owner activate an account the
stranger controls, at the owner's own verified address. The person who redeems
the link sets the name and password.

Revision ID: 059_email_verification
Revises: 058_single_openreview_id
"""
import sqlalchemy as sa
from alembic import op

revision = "059_email_verification"
down_revision = "058_single_openreview_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "human_account",
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "human_account", sa.Column("openreview_name", sa.String(), nullable=True)
    )
    op.add_column(
        "human_account",
        sa.Column("last_signup_notice_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "human_account",
        sa.Column(
            "last_verification_mail_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    op.create_table(
        "email_verification_token",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "human_account_id",
            sa.UUID(),
            sa.ForeignKey("human_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("pending_openreview_id", sa.String(), nullable=False),
        sa.Column("pending_openreview_name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            # clock_timestamp(), not now(): now() is the transaction start time,
            # and which claim is newest decides which identity the next link
            # carries.
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_email_verification_token_human_account_id",
        "email_verification_token",
        ["human_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_token_human_account_id",
        table_name="email_verification_token",
    )
    op.drop_table("email_verification_token")
    op.drop_column("human_account", "last_verification_mail_at")
    op.drop_column("human_account", "last_signup_notice_at")
    op.drop_column("human_account", "openreview_name")
    op.drop_column("human_account", "email_verified")
