"""Add provider-neutral subscription state and webhook idempotency."""

from alembic import op
import sqlalchemy as sa


revision = "0014_client_subscriptions"
down_revision = "0013_scheduled_job_parameters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "client_subscriptions" not in tables:
        op.create_table(
            "client_subscriptions",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("client_id", sa.String(length=16), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="trial"),
            sa.Column("plan", sa.String(length=80), nullable=False, server_default="agency"),
            sa.Column("provider", sa.String(length=40), nullable=False, server_default="manual"),
            sa.Column("provider_customer_id", sa.String(length=160), nullable=True),
            sa.Column("provider_subscription_id", sa.String(length=160), nullable=True),
            sa.Column("current_period_start", sa.DateTime(), nullable=True),
            sa.Column("current_period_end", sa.DateTime(), nullable=True),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("client_id"),
        )
        op.create_index("ix_client_subscriptions_client_id", "client_subscriptions", ["client_id"])
    if "subscription_events" not in tables:
        op.create_table(
            "subscription_events",
            sa.Column("id", sa.String(length=40), primary_key=True),
            sa.Column("event_id", sa.String(length=160), nullable=False),
            sa.Column("client_id", sa.String(length=16), sa.ForeignKey("clients.id"), nullable=True),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("event_id"),
        )
        op.create_index("ix_subscription_events_event_id", "subscription_events", ["event_id"])
        op.create_index("ix_subscription_events_client_id", "subscription_events", ["client_id"])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
