"""Bootstrap the complete Max metadata schema.

The application models are the source of truth for the initial schema. Future
changes must use explicit Alembic revisions rather than changing production
tables during application startup.
"""

from alembic import op
from app.database import Base
from app import models  # noqa: F401 - register all models


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Max preserves historical data; destructive downgrade is intentionally not automatic.
    raise RuntimeError("Max migrations do not support destructive downgrades")
