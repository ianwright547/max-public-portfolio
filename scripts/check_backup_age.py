"""Fail-closed freshness and integrity check for a Max backup artifact.

Usage:
    python scripts/check_backup_age.py --path /secure/backups/max-latest.dump --max-age-hours 26
    python scripts/check_backup_age.py --path /secure/backups/max.dump --max-age-hours 26 --sha256 HEX
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


class BackupCheckFailure(RuntimeError):
    """The backup is missing, unsafe, stale, or does not match its checksum."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_backup(
    path: Path,
    *,
    max_age_hours: float,
    expected_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return safe metadata or raise a specific operator-facing failure."""
    if max_age_hours <= 0:
        raise BackupCheckFailure("max_age_hours must be positive")
    if path.is_symlink() or not path.is_file():
        raise BackupCheckFailure("backup artifact is missing or is not a regular file")
    stat = path.stat()
    if stat.st_size <= 0:
        raise BackupCheckFailure("backup artifact is empty")
    if stat.st_mode & 0o077:
        raise BackupCheckFailure("backup artifact permissions are too broad; require owner-only access")
    current = now or datetime.now(timezone.utc)
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    age_hours = (current - modified).total_seconds() / 3600
    if age_hours < 0:
        raise BackupCheckFailure("backup artifact modification time is in the future")
    if age_hours > max_age_hours:
        raise BackupCheckFailure(f"backup artifact is stale ({age_hours:.2f} hours old)")
    digest = _sha256(path)
    if expected_sha256 is not None:
        expected = expected_sha256.strip().casefold()
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise BackupCheckFailure("expected SHA-256 must be 64 hexadecimal characters")
        if digest != expected:
            raise BackupCheckFailure("backup artifact SHA-256 does not match the expected value")
    return {
        "status": "healthy",
        "path": str(path),
        "bytes": stat.st_size,
        "sha256": digest,
        "age_hours": round(age_hours, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--max-age-hours", required=True, type=float)
    parser.add_argument("--sha256", help="Optional expected SHA-256 checksum")
    args = parser.parse_args(argv)
    try:
        result = check_backup(args.path, max_age_hours=args.max_age_hours, expected_sha256=args.sha256)
    except BackupCheckFailure as error:
        print(f"Backup check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
