"""Restore a Max PostgreSQL backup into an explicitly isolated target.

This command is intentionally fail-closed. It will not run without an explicit
confirmation flag and it refuses a target that resolves to the configured
production database. It never prints either database URL.

Usage:
    python scripts/restore_database_rehearsal.py \
      --backup /secure/backups/max.dump \
      --target-url postgresql://restore_user:password@restore-db/max_restore \
      --confirm-isolated-target
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlparse


class RestoreFailure(RuntimeError):
    """The restore rehearsal could not be safely completed."""


def _require_postgres_url(value: str, label: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"} or not parsed.hostname or not parsed.path.strip("/"):
        raise RestoreFailure(f"{label} must be a PostgreSQL URL with a database name")
    return value.strip()


def _target_identity(value: str) -> tuple[str, int, str]:
    parsed = urlparse(value.replace("+psycopg", "", 1))
    return (
        (parsed.hostname or "").casefold(),
        parsed.port or 5432,
        unquote(parsed.path.strip("/")).casefold(),
    )


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RestoreFailure(f"{name} is required for restore rehearsal")
    return path


def restore_rehearsal(
    backup: Path,
    target_url: str,
    *,
    production_url: str,
    confirm_isolated_target: bool,
) -> dict[str, object]:
    if not confirm_isolated_target:
        raise RestoreFailure("refusing restore without --confirm-isolated-target")
    if backup.is_symlink() or not backup.is_file() or backup.stat().st_size <= 0:
        raise RestoreFailure("backup artifact is missing, empty, or is a symbolic link")
    target = _require_postgres_url(target_url, "target URL")
    production = _require_postgres_url(production_url, "MAX_DATABASE_URL")
    if _target_identity(target) == _target_identity(production):
        raise RestoreFailure("restore target matches the configured production database")
    pg_restore = _require_binary("pg_restore")
    psql = _require_binary("psql")
    try:
        subprocess.run(
            [
                pg_restore,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                target,
                str(backup),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            [psql, target, "--no-psqlrc", "-Atqc", "SELECT 1"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as error:
        raise RestoreFailure("PostgreSQL restore rehearsal failed") from error
    return {"status": "verified", "backup": str(backup), "target_database": _target_identity(target)[2]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--confirm-isolated-target", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.config import read_database_url

        result = restore_rehearsal(
            args.backup,
            args.target_url,
            production_url=read_database_url(),
            confirm_isolated_target=args.confirm_isolated_target,
        )
    except RestoreFailure as error:
        print(f"Restore rehearsal failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
