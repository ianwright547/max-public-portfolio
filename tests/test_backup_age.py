"""Backup monitoring fails closed on stale or unsafe artifacts."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import check_backup_age


def _owner_only(path: Path) -> None:
    path.chmod(0o600)


def test_backup_check_returns_integrity_metadata(tmp_path: Path) -> None:
    path = tmp_path / "max.dump"
    path.write_bytes(b"backup")
    _owner_only(path)
    now = datetime.now(timezone.utc)
    result = check_backup_age.check_backup(path, max_age_hours=24, now=now + timedelta(minutes=1))

    assert result["status"] == "healthy"
    assert result["bytes"] == 6
    assert len(result["sha256"]) == 64
    assert result["age_hours"] >= 0


def test_backup_check_rejects_stale_and_broad_permissions(tmp_path: Path) -> None:
    path = tmp_path / "max.dump"
    path.write_bytes(b"backup")
    _owner_only(path)
    with pytest.raises(check_backup_age.BackupCheckFailure, match="stale"):
        check_backup_age.check_backup(
            path,
            max_age_hours=24,
            now=datetime.now(timezone.utc) + timedelta(hours=25),
        )

    path.chmod(0o644)
    with pytest.raises(check_backup_age.BackupCheckFailure, match="permissions"):
        check_backup_age.check_backup(path, max_age_hours=24)


def test_backup_check_rejects_checksum_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "max.dump"
    path.write_bytes(b"backup")
    _owner_only(path)
    with pytest.raises(check_backup_age.BackupCheckFailure, match="SHA-256"):
        check_backup_age.check_backup(path, max_age_hours=24, expected_sha256="0" * 64)
