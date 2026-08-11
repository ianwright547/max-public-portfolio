"""Run read-only smoke tests against a deployed Max instance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class SmokeFailure(RuntimeError):
    """One safe deployment failure that never includes response bodies."""


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    path: str


def deployment_origin(value: str, allow_http_localhost: bool = False) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    valid_scheme = parsed.scheme == "https" or (
        allow_http_localhost and parsed.scheme == "http" and parsed.hostname in local_hosts
    )
    if not valid_scheme or not parsed.netloc or parsed.path not in {"", "/"}:
        raise SmokeFailure("base_url_must_be_https_origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SmokeFailure("base_url_must_not_include_credentials_query_or_fragment")
    return candidate


def fetch_json(url: str, timeout_seconds: float, headers: dict[str, str] | None = None) -> dict:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "max-deployment-smoke-test/1", **(headers or {})},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise SmokeFailure(f"unexpected_http_status_{response.status}")
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise SmokeFailure("response_is_not_json")
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise SmokeFailure(f"http_error_{error.code}") from error
    except URLError as error:
        raise SmokeFailure("deployment_unreachable") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmokeFailure("invalid_json_response") from error


def fetch_status(url: str, timeout_seconds: float) -> int:
    """Return an endpoint status without logging its response body."""
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "max-deployment-smoke-test/1"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return int(response.status)
    except HTTPError as error:
        return int(error.code)
    except URLError as error:
        raise SmokeFailure("deployment_unreachable") from error


def validate_auth_boundary(status: int) -> None:
    if status != 401:
        raise SmokeFailure(f"unauthenticated_data_route_status_{status}")


def validate_health(body: dict) -> None:
    if body.get("status") != "ok":
        raise SmokeFailure("health_status_not_ok")


def validate_health_details(body: dict) -> None:
    if body.get("status") != "ok" or body.get("database") != "ok":
        raise SmokeFailure("detailed_health_not_ok")
    if (body.get("onboarding") or {}).get("stale_runs") != 0:
        raise SmokeFailure("stale_onboarding_runs_detected")
    if (body.get("scheduler") or {}).get("failed_jobs") != 0:
        raise SmokeFailure("failed_scheduled_jobs_detected")
    if (body.get("scheduler") or {}).get("stale_jobs", 0) != 0:
        raise SmokeFailure("stale_scheduled_jobs_detected")


def validate_readiness(body: dict, profile: str) -> None:
    if body.get("profile") != profile:
        raise SmokeFailure("readiness_profile_mismatch")
    if body.get("status") != "ready" or (body.get("summary") or {}).get("blocked") != 0:
        raise SmokeFailure("deployment_not_ready")
    if profile == "full":
        observed = {str(check.get("key")) for check in body.get("checks", []) if isinstance(check, dict)}
        required = {
            "scheduler_operational_state",
            "archived_client_job_safety",
            "persisted_integration_health",
        }
        if not required.issubset(observed):
            raise SmokeFailure("readiness_contract_outdated")


def validate_api_contract(body: dict) -> None:
    """Confirm the deployed build exposes the fulfillment surfaces we ship."""
    paths = body.get("paths")
    if not isinstance(paths, dict):
        raise SmokeFailure("openapi_paths_missing")
    required = {
        "/clients/{client_id}/reports",
        "/clients/{client_id}/daily-plan",
        "/tasks/{task_id}/website-generation-preview",
        "/tasks/{task_id}/decision",
        "/tasks/{task_id}/browser-approval",
        "/reports/{report_id}/pdf",
        "/reports/{report_id}/plan-items/{horizon}/{item_index}/task",
        "/jobs/run-due",
        "/jobs/provider-health",
    }
    missing = sorted(required.difference(paths))
    if missing:
        raise SmokeFailure("api_contract_missing_" + "_".join(path.strip("/").replace("/", "-") for path in missing))


def validate_provider_health(body: dict) -> None:
    if body.get("status") != "verified":
        failed_clients = [
            str(item.get("client_id"))
            for item in body.get("clients", [])
            if isinstance(item, dict) and item.get("status") == "failed"
        ]
        suffix = "_" + "_".join(failed_clients[:3]) if failed_clients else ""
        raise SmokeFailure("active_client_provider_health_failed" + suffix)


def run_smoke_test(
    base_url: str,
    profile: str = "core",
    timeout_seconds: float = 10.0,
    allow_http_localhost: bool = False,
    provider_health_secret: str | None = None,
) -> list[str]:
    if timeout_seconds <= 0:
        raise SmokeFailure("timeout_must_be_positive")
    origin = deployment_origin(base_url, allow_http_localhost)
    checks = [
        SmokeCheck("health", "/health"),
        SmokeCheck("health_details", "/health/details"),
        SmokeCheck("readiness", f"/health/readiness?profile={profile}"),
        SmokeCheck("auth_boundary", "/clients"),
        SmokeCheck("api_contract", "/openapi.json"),
    ]
    completed = []
    for check in checks:
        if check.name == "auth_boundary":
            validate_auth_boundary(fetch_status(f"{origin}{check.path}", timeout_seconds))
            completed.append(check.name)
            continue
        body = fetch_json(f"{origin}{check.path}", timeout_seconds)
        if check.name == "health":
            validate_health(body)
        elif check.name == "health_details":
            validate_health_details(body)
        elif check.name == "readiness":
            validate_readiness(body, profile)
        else:
            validate_api_contract(body)
        completed.append(check.name)
    if provider_health_secret:
        provider_body = fetch_json(
            f"{origin}/jobs/provider-health",
            timeout_seconds,
            headers={"Authorization": f"Bearer {provider_health_secret}"},
        )
        validate_provider_health(provider_body)
        completed.append("active_client_provider_health")
    return completed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="HTTPS deployment origin, without a path")
    parser.add_argument("--profile", choices=("core", "full"), default="core")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--allow-http-localhost", action="store_true")
    parser.add_argument(
        "--provider-health",
        action="store_true",
        help="run the scheduler-secret-protected active-client provider sweep using MAX_PROVIDER_HEALTH_SECRET",
    )
    args = parser.parse_args(argv)
    if args.provider_health and not os.environ.get("MAX_PROVIDER_HEALTH_SECRET", "").strip():
        print("[failed] provider_health_secret_missing", file=sys.stderr)
        return 1
    try:
        completed = run_smoke_test(
            args.base_url,
            profile=args.profile,
            timeout_seconds=args.timeout,
            allow_http_localhost=args.allow_http_localhost,
            provider_health_secret=(
                os.environ.get("MAX_PROVIDER_HEALTH_SECRET", "").strip()
                if args.provider_health
                else None
            ),
        )
    except SmokeFailure as error:
        print(f"[failed] {error}", file=sys.stderr)
        return 1
    for name in completed:
        print(f"[passed] {name}")
    print(f"\nDeployment smoke test passed ({args.profile}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
