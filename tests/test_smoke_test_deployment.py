"""Post-deployment checks remain read-only, strict, and safe to print."""

import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from scripts import smoke_test_deployment


class FakeResponse:
    def __init__(self, body: dict, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def healthy_responses(profile: str = "full") -> list[dict]:
    return [
        {"status": "ok"},
        {
            "status": "ok",
            "database": "ok",
        "scheduler": {"due_jobs": 0, "failed_jobs": 0, "running_jobs": 0, "stale_jobs": 0},
            "onboarding": {"stale_runs": 0},
        },
        {
            "status": "ready",
            "profile": profile,
            "summary": {"passed": 15, "blocked": 0, "total": 15},
            "checks": [
                {"key": "scheduler_operational_state"},
                {"key": "archived_client_job_safety"},
                {"key": "persisted_integration_health"},
            ],
        },
        {"paths": {
            "/clients/{client_id}/reports": {},
            "/clients/{client_id}/daily-plan": {},
            "/tasks/{task_id}/website-generation-preview": {},
            "/tasks/{task_id}/decision": {},
            "/tasks/{task_id}/browser-approval": {},
            "/reports/{report_id}/pdf": {},
            "/reports/{report_id}/plan-items/{horizon}/{item_index}/task": {},
            "/jobs/run-due": {},
            "/jobs/provider-health": {},
        }},
    ]


def test_smoke_test_calls_only_expected_get_endpoints(monkeypatch) -> None:
    responses = iter(healthy_responses())
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/clients"):
            raise HTTPError(request.full_url, 401, "unauthorized", hdrs=None, fp=None)
        return FakeResponse(next(responses))

    monkeypatch.setattr(smoke_test_deployment, "urlopen", fake_urlopen)
    completed = smoke_test_deployment.run_smoke_test(
        "https://max.example.test/", profile="full", timeout_seconds=4.0
    )

    assert completed == ["health", "health_details", "readiness", "auth_boundary", "api_contract"]
    assert [request.full_url for request, _ in requests] == [
        "https://max.example.test/health",
        "https://max.example.test/health/details",
        "https://max.example.test/health/readiness?profile=full",
        "https://max.example.test/clients",
        "https://max.example.test/openapi.json",
    ]
    assert all(request.get_method() == "GET" for request, _ in requests)
    assert all(timeout == 4.0 for _, timeout in requests)


def test_smoke_test_can_run_scheduler_protected_active_client_provider_health(monkeypatch) -> None:
    responses = iter(
        healthy_responses()
        + [{"status": "verified", "clients": [{"client_id": "client_1", "status": "verified", "summary": {}}]}]
    )
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/clients"):
            raise HTTPError(request.full_url, 401, "unauthorized", hdrs=None, fp=None)
        return FakeResponse(next(responses))

    monkeypatch.setattr(smoke_test_deployment, "urlopen", fake_urlopen)
    completed = smoke_test_deployment.run_smoke_test(
        "https://max.example.test", profile="full", provider_health_secret="scheduler-secret"
    )
    assert completed[-1] == "active_client_provider_health"
    provider_request = requests[-1]
    assert provider_request.full_url == "https://max.example.test/jobs/provider-health"
    assert provider_request.get_header("Authorization") == "Bearer scheduler-secret"


def test_provider_health_validation_rejects_failed_client() -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure, match="active_client_provider_health_failed"):
        smoke_test_deployment.validate_provider_health(
            {"status": "failed", "clients": [{"client_id": "client_9", "status": "failed"}]}
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://max.example.test",
        "https://user:password@max.example.test",
        "https://max.example.test/app",
        "https://max.example.test?token=secret",
    ],
)
def test_smoke_test_rejects_unsafe_or_non_origin_urls(url: str) -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure):
        smoke_test_deployment.deployment_origin(url)


def test_local_http_requires_explicit_opt_in() -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure):
        smoke_test_deployment.deployment_origin("http://127.0.0.1:8000")

    assert (
        smoke_test_deployment.deployment_origin(
            "http://127.0.0.1:8000/", allow_http_localhost=True
        )
        == "http://127.0.0.1:8000"
    )


def test_timeout_must_be_positive() -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure, match="timeout_must_be_positive"):
        smoke_test_deployment.run_smoke_test("https://max.example.test", timeout_seconds=0)


@pytest.mark.parametrize(
    ("details", "reason"),
    [
        (
            {
                "status": "ok",
                "database": "ok",
                "scheduler": {"failed_jobs": 0},
                "onboarding": {"stale_runs": 1},
            },
            "stale_onboarding_runs_detected",
        ),
        (
            {
                "status": "ok",
                "database": "ok",
                "scheduler": {"failed_jobs": 2},
                "onboarding": {"stale_runs": 0},
            },
            "failed_scheduled_jobs_detected",
        ),
    ],
)
def test_detailed_health_blocks_stale_work_and_failed_jobs(details: dict, reason: str) -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure, match=reason):
        smoke_test_deployment.validate_health_details(details)


def test_readiness_requires_matching_zero_blocker_profile() -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure, match="readiness_profile_mismatch"):
        smoke_test_deployment.validate_readiness(
            {"status": "ready", "profile": "core", "summary": {"blocked": 0}}, "full"
        )


@pytest.mark.parametrize("status", [200, 403, 404, 500])
def test_auth_boundary_rejects_anything_other_than_unauthorized(status: int) -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure, match="unauthenticated_data_route_status"):
        smoke_test_deployment.validate_auth_boundary(status)


def test_auth_boundary_accepts_unauthorized() -> None:
    smoke_test_deployment.validate_auth_boundary(401)
    with pytest.raises(smoke_test_deployment.SmokeFailure, match="deployment_not_ready"):
        smoke_test_deployment.validate_readiness(
            {"status": "not_ready", "profile": "full", "summary": {"blocked": 1}}, "full"
        )


def test_full_readiness_rejects_an_outdated_contract() -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure, match="readiness_contract_outdated"):
        smoke_test_deployment.validate_readiness(
            {"status": "ready", "profile": "full", "summary": {"blocked": 0}, "checks": []},
            "full",
        )


def test_api_contract_requires_fulfillment_surfaces() -> None:
    with pytest.raises(smoke_test_deployment.SmokeFailure, match="api_contract_missing"):
        smoke_test_deployment.validate_api_contract({"paths": {"/health": {}}})
