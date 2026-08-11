"""Add deduplicated evidence-backed daily client plans."""

from alembic import op
import sqlalchemy as sa


revision = "0010_daily_client_plans"
down_revision = "0009_slack_memories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "daily_client_plans" in inspector.get_table_names():
        return
    op.create_table(
        "daily_client_plans",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("client_id", sa.String(length=16), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("depth", sa.String(length=20), nullable=False),
        sa.Column("focus", sa.String(length=30), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("source_summary", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "plan_date"),
    )
    for column in ("client_id", "plan_date", "updated_at"):
        op.create_index(f"ix_daily_client_plans_{column}", "daily_client_plans", [column])


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
