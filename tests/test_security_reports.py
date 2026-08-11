"""Phase 21/22 baseline security and report artifact tests."""

from fastapi.testclient import TestClient

from app.main import app


def test_security_headers_are_present() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_unknown_report_download_is_not_exposed() -> None:
    with TestClient(app) as client:
        response = client.get("/reports/report_missing/download")

    assert response.status_code == 404
