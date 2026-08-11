"""Add explicit report approval metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0003_report_approval"
down_revision = "0002_prompt_artifact_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("reports")}
    with op.batch_alter_table("reports") as batch:
        if "status" not in columns:
            batch.add_column(sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"))
        if "approved_by" not in columns:
            batch.add_column(sa.Column("approved_by", sa.String(length=200), nullable=True))
        if "approved_at" not in columns:
            batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
