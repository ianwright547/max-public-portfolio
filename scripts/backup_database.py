"""Create and verify one production PostgreSQL backup artifact.

The script is intentionally explicit about its destination and never prints the
database URL. It creates a custom-format dump, verifies it with pg_restore, and
prints only the artifact metadata needed for an operator or backup monitor.

Usage:
    python scripts/backup_database.py --output /secure/backups/max-2026-08-21.dump
    python scripts/backup_database.py --output /secure/backups/max.dump --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


class BackupFailure(RuntimeError):
    """The backup could not be created or independently verified."""


def _database_url() -> str:
    # Import lazily so `--help` remains usable even when application settings
    # are incomplete on an operator workstation.
    from app.config import read_database_url

    value = read_database_url().strip()
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise BackupFailure("MAX_DATABASE_URL must be a PostgreSQL URL")
    return value


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BackupFailure(f"{name} is required for database backup verification")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(output: Path, *, force: bool = False) -> dict[str, object]:
    """Create one custom-format dump and verify its readable archive index."""
    if output.exists() and not force:
        raise BackupFailure("backup destination already exists; pass --force to replace it")
    if output.is_symlink():
        raise BackupFailure("backup destination must not be a symbolic link")
    output.parent.mkdir(parents=True, exist_ok=True)
    database_url = _database_url()
    pg_dump = _require_binary("pg_dump")
    pg_restore = _require_binary("pg_restore")

    try:
        subprocess.run(
            [
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(output),
                "--dbname",
                database_url,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if not output.is_file() or output.stat().st_size == 0:
            raise BackupFailure("pg_dump did not create a non-empty backup artifact")
        # Listing the archive is a read-only structural verification; it does
        # not restore or mutate the destination database.
        subprocess.run(
            [pg_restore, "--list", str(output)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise BackupFailure("PostgreSQL backup command failed") from error
    except OSError as error:
        raise BackupFailure("PostgreSQL backup command could not be started") from error

    try:
        os.chmod(output, 0o600)
    except OSError as error:
        raise BackupFailure("backup was created but its permissions could not be restricted") from error
    return {
        "status": "verified",
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Explicit destination for the backup artifact")
    parser.add_argument("--force", action="store_true", help="Replace an existing regular backup file")
    args = parser.parse_args(argv)
    try:
        result = create_backup(args.output, force=args.force)
    except BackupFailure as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
