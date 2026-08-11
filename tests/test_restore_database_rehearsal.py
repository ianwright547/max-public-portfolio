from pathlib import Path

from scripts import restore_database_rehearsal


def _backup(tmp_path: Path) -> Path:
    path = tmp_path / "max.dump"
    path.write_bytes(b"backup")
    return path


def test_restore_requires_explicit_isolated_confirmation(tmp_path):
    try:
        restore_database_rehearsal.restore_rehearsal(
            _backup(tmp_path),
            "postgresql://restore@restore.example/max_restore",
            production_url="postgresql://prod@prod.example/max",
            confirm_isolated_target=False,
        )
    except restore_database_rehearsal.RestoreFailure as error:
        assert "confirm" in str(error)
    else:  # pragma: no cover
        raise AssertionError("restore should require confirmation")


def test_restore_rejects_production_target(tmp_path):
    try:
        restore_database_rehearsal.restore_rehearsal(
            _backup(tmp_path),
            "postgresql://other:secret@db.example/max",
            production_url="postgresql://prod:secret@db.example/max",
            confirm_isolated_target=True,
        )
    except restore_database_rehearsal.RestoreFailure as error:
        assert "production" in str(error)
    else:  # pragma: no cover
        raise AssertionError("production target must be rejected")


def test_restore_runs_pg_restore_and_connectivity_check(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(restore_database_rehearsal, "_require_binary", lambda name: name)

    def run(command, **kwargs):
        calls.append(command)

    monkeypatch.setattr(restore_database_rehearsal.subprocess, "run", run)
    result = restore_database_rehearsal.restore_rehearsal(
        _backup(tmp_path),
        "postgresql://restore:secret@restore.example/max_restore",
        production_url="postgresql://prod:secret@prod.example/max",
        confirm_isolated_target=True,
    )
    assert result["status"] == "verified"
    assert calls[0][:2] == ["pg_restore", "--clean"]
    assert calls[1][:2] == ["psql", "postgresql://restore:secret@restore.example/max_restore"]
