"""Add durable agency members and role mappings."""

from alembic import op
import sqlalchemy as sa


revision = "0023_agency_members"
down_revision = "0022_outcome_measurements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agency_members" in inspector.get_table_names():
        return
    op.create_table(
        "agency_members",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="operator"),
        sa.Column("slack_user_id", sa.String(length=40), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("slack_user_id"),
    )
    op.create_index("ix_agency_members_email", "agency_members", ["email"], unique=True)
    op.create_index("ix_agency_members_role", "agency_members", ["role"])
    op.create_index("ix_agency_members_slack_user_id", "agency_members", ["slack_user_id"], unique=True)
    op.create_index("ix_agency_members_active", "agency_members", ["active"])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
