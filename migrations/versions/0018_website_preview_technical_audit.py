"""Persist deterministic technical checks for generated website previews."""

from alembic import op
import sqlalchemy as sa


revision = "0018_website_preview_technical_audit"
down_revision = "0017_browser_control_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("website_previews")}
    if "technical_audit" not in columns:
        with op.batch_alter_table("website_previews") as batch:
            batch.add_column(
                sa.Column("technical_audit", sa.JSON(), nullable=False, server_default="{}")
            )


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
