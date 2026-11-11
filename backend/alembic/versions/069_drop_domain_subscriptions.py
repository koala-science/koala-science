"""Drop domain subscriptions and the "new paper in your domain" notification.

Subscribing did nothing but trigger that notification, so both go. Postgres
cannot drop an enum value, so PAPER_IN_DOMAIN stays in the type; its rows are
deleted, since code from this revision on cannot load them. The downgrade
recreates the table empty: the subscriptions and notifications are gone.

Revision ID: 069_drop_domain_subscriptions
Revises: 068_argument_notifications
"""
import sqlalchemy as sa
from alembic import op

revision = "069_drop_domain_subscriptions"
down_revision = "068_argument_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM notification WHERE notification_type::text = 'PAPER_IN_DOMAIN'")
    op.drop_table("subscription")


def downgrade() -> None:
    op.create_table(
        "subscription",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("domain_id", sa.Uuid(), sa.ForeignKey("domain.id"), nullable=False),
        sa.Column("subscriber_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("domain_id", "subscriber_id", name="uq_subscription_domain_subscriber"),
    )
