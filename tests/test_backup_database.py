"""Production backup artifacts are explicit, verified, and secret-free."""

from pathlib import Path

import pytest

from scripts import backup_database


def test_create_backup_verifies_archive_and_restricts_permissions(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "nested" / "max.dump"
    calls: list[list[str]] = []

    monkeypatch.setattr(backup_database, "_database_url", lambda: "postgresql://hidden.example/max")
    monkeypatch.setattr(backup_database.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0].endswith("pg_dump"):
            output.write_bytes(b"verified custom archive")

    monkeypatch.setattr(backup_database.subprocess, "run", fake_run)
    result = backup_database.create_backup(output)

    assert result["status"] == "verified"
    assert result["bytes"] == len(b"verified custom archive")
    assert len(result["sha256"]) == 64
    assert calls[0][-1] == "postgresql://hidden.example/max"
    assert calls[1][:2] == ["/usr/bin/pg_restore", "--list"]
    assert output.stat().st_mode & 0o777 == 0o600


def test_backup_does_not_overwrite_without_force(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "max.dump"
    output.write_bytes(b"existing")
    with pytest.raises(backup_database.BackupFailure, match="already exists"):
        backup_database.create_backup(output)


def test_backup_requires_postgres(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.config.read_database_url", lambda: "sqlite:////tmp/max.db")
    with pytest.raises(backup_database.BackupFailure, match="PostgreSQL URL"):
        backup_database.create_backup(tmp_path / "max.dump")
