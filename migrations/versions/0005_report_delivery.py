"""Add audited, retry-safe report delivery records."""

from alembic import op
import sqlalchemy as sa


revision = "0005_report_delivery"
down_revision = "0004_google_business_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "report_deliveries" not in inspector.get_table_names():
        op.create_table(
            "report_deliveries",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("operation_key", sa.String(length=120), nullable=False, unique=True),
            sa.Column("report_id", sa.String(length=24), sa.ForeignKey("reports.id"), nullable=False, unique=True),
            sa.Column("client_id", sa.String(length=32), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("channel_connection_id", sa.String(length=32), sa.ForeignKey("slack_channel_connections.id"), nullable=False),
            sa.Column("channel_id", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("message_timestamp", sa.String(length=40), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_report_deliveries_operation_key", "report_deliveries", ["operation_key"], unique=True)
        op.create_index("ix_report_deliveries_report_id", "report_deliveries", ["report_id"], unique=True)
        op.create_index("ix_report_deliveries_client_id", "report_deliveries", ["client_id"])
        op.create_index("ix_report_deliveries_channel_connection_id", "report_deliveries", ["channel_connection_id"])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
