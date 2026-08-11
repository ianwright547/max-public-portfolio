"""Phase 13 tests for safe, repeatable website-import preparation."""

import json
from pathlib import Path

import pytest

from scripts.import_vercel_clients import read_manifest


MANIFEST = Path(__file__).parent.parent / "data" / "vercel_client_import.json"


def test_confirmed_manifest_has_unique_clients_and_projects() -> None:
    records = read_manifest(MANIFEST)

    assert len(records) == 13
    assert len({record["business_name"].casefold() for record in records}) == 13
    assert len({record["external_project_id"] for record in records}) == 13
    assert all(record["production_url"].startswith("https://") for record in records)


def test_manifest_rejects_duplicate_client_or_project(tmp_path: Path) -> None:
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records.append(dict(records[0]))
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(records), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate business name"):
        read_manifest(duplicate_path)


def test_manifest_rejects_non_https_website(tmp_path: Path) -> None:
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records[0]["production_url"] = "http://unsafe.example.com"
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(records), encoding="utf-8")

    with pytest.raises(ValueError, match="HTTPS"):
        read_manifest(invalid_path)
