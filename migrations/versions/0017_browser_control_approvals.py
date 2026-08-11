"""Persist explicit owner approval for browser-control fallback."""

from alembic import op
import sqlalchemy as sa


revision = "0017_browser_control_approvals"
down_revision = "0016_website_preview_comparisons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    missing = {
        "browser_control_approved_by": sa.Column("browser_control_approved_by", sa.String(length=200), nullable=True),
        "browser_control_approved_at": sa.Column("browser_control_approved_at", sa.DateTime(), nullable=True),
        "browser_control_approval_reason": sa.Column("browser_control_approval_reason", sa.String(length=1000), nullable=True),
    }
    if any(name not in columns for name in missing):
        with op.batch_alter_table("tasks") as batch:
            for name, column in missing.items():
                if name not in columns:
                    batch.add_column(column)


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
