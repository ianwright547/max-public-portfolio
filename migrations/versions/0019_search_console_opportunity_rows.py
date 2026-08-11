"""Persist bounded Search Console query and page opportunity rows."""

from alembic import op
import sqlalchemy as sa


revision = "0019_search_console_opportunity_rows"
down_revision = "0018_website_preview_technical_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("search_console_connections")}
    additions = {
        "last_query_rows": sa.Column("last_query_rows", sa.JSON(), nullable=False, server_default="[]"),
        "last_page_rows": sa.Column("last_page_rows", sa.JSON(), nullable=False, server_default="[]"),
        "last_query_start_date": sa.Column("last_query_start_date", sa.Date(), nullable=True),
        "last_query_end_date": sa.Column("last_query_end_date", sa.Date(), nullable=True),
    }
    if any(name not in columns for name in additions):
        with op.batch_alter_table("search_console_connections") as batch:
            for name, column in additions.items():
                if name not in columns:
                    batch.add_column(column)


def downgrade() -> None:
    raise RuntimeError("Max migrations do not support destructive downgrades")
