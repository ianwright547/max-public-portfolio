"""Browser fallback submits work only through the configured worker boundary."""

from fastapi.testclient import TestClient

from app.main import app
from app.routes import browser_execution
from tests.test_fulfillment import make_eligible_task


class FakeWorker:
    def submit(self, **_kwargs):
        return {"job_id": "browser-job-1", "status": "queued"}

    def poll(self, job_id):
        assert job_id == "browser-job-1"
        return {"status": "completed", "evidence": {"screenshot": "worker-evidence-ref"}}


def test_browser_fallback_submits_and_polls_worker_job(monkeypatch) -> None:
    monkeypatch.setattr(browser_execution, "BrowserWorkerAdapter", FakeWorker)
    with TestClient(app) as client:
        _, _, task_id = make_eligible_task(client, "Browser Fallback", ready=True)
        blocked = client.post(
            f"/tasks/{task_id}/browser-executions",
            json={
                "operation_key": "browser-execution-blocked",
                "target_url": "https://example.com",
                "instructions": "Inspect the approved page and report the visible issue.",
            },
        )
        approved = client.post(
            f"/tasks/{task_id}/browser-approval",
            json={"approved_by": "Agency Owner", "reason": "Inspect this exact page for the approved task."},
        )
        submitted = client.post(
            f"/tasks/{task_id}/browser-executions",
            json={
                "operation_key": "browser-execution-1",
                "target_url": "https://example.com",
                "instructions": "Inspect the approved page and report the visible issue.",
            },
        )
        polled = client.post(f"/browser-executions/{submitted.json()['id']}/poll")

    assert submitted.status_code == 201
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "explicit_browser_control_approval_required"
    assert approved.status_code == 200
    assert approved.json()["browser_control_approved_by"] == "Agency Owner"
    assert submitted.json()["status"] == "running"
    assert submitted.json()["evidence"]["worker_job_id"] == "browser-job-1"
    assert polled.status_code == 200
    assert polled.json()["status"] == "completed"
    assert polled.json()["evidence"]["worker_result"]["screenshot"] == "worker-evidence-ref"


def test_browser_fallback_requires_worker_configuration(monkeypatch) -> None:
    # The application-level boundary is tested through the adapter's own
    # configuration behavior; no provider network call is made here.
    from app.browser_execution_service import BrowserExecutionError, BrowserWorkerAdapter

    monkeypatch.setenv("BROWSER_WORKER_URL", "")
    monkeypatch.setenv("BROWSER_WORKER_TOKEN", "")
    try:
        BrowserWorkerAdapter()
    except BrowserExecutionError as error:
        assert error.code == "browser_worker_configuration_missing"
    else:
        raise AssertionError("missing browser worker configuration was accepted")
