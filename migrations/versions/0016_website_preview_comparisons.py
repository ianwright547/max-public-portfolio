"""Persist file-level comparisons between website preview drafts."""

from alembic import op
import sqlalchemy as sa


revision = "0016_website_preview_comparisons"
down_revision = "0015_website_previews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("website_previews")}
    if "comparison" not in columns:
        with op.batch_alter_table("website_previews") as batch:
            batch.add_column(sa.Column("comparison", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
