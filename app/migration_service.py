"""Explicit production migration runner for environments with runtime-only secrets."""

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory


def run_production_migrations() -> dict[str, str]:
    """Upgrade to the repository head without returning connection information."""
    root = Path(__file__).resolve().parents[1]
    config = AlembicConfig(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    expected_revision = ScriptDirectory.from_config(config).get_current_head()
    command.upgrade(config, "head")
    return {"status": "current", "revision": expected_revision}
