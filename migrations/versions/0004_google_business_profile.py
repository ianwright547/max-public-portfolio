"""Add client-bound Google Business Profile connections and posts."""

from alembic import op
import sqlalchemy as sa


revision = "0004_google_business_profile"
down_revision = "0003_report_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "google_business_profile_connections" not in inspector.get_table_names():
        op.create_table(
            "google_business_profile_connections",
            sa.Column("id", sa.String(length=34), primary_key=True),
            sa.Column("client_id", sa.String(length=32), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("account_id", sa.String(length=120), nullable=False),
            sa.Column("location_id", sa.String(length=160), nullable=False),
            sa.Column("location_name", sa.String(length=300), nullable=False),
            sa.Column("connection_status", sa.String(length=30), nullable=False, server_default="connected"),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("linked_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("client_id"),
            sa.UniqueConstraint("account_id", "location_id"),
        )
    if "google_business_profile_posts" not in inspector.get_table_names():
        op.create_table(
            "google_business_profile_posts",
            sa.Column("id", sa.String(length=30), primary_key=True),
            sa.Column("operation_key", sa.String(length=160), nullable=False),
            sa.Column("client_id", sa.String(length=32), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("connection_id", sa.String(length=34), sa.ForeignKey("google_business_profile_connections.id"), nullable=False),
            sa.Column("summary", sa.String(length=1500), nullable=False),
            sa.Column("call_to_action_url", sa.String(length=1000), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("approved_by", sa.String(length=200), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("external_post_id", sa.String(length=300), nullable=True),
            sa.Column("error_code", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("operation_key"),
        )


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
