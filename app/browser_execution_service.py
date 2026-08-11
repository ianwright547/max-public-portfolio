"""HTTP boundary for an external browser-control worker."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx


class BrowserExecutionError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


SECRET_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:TOKEN|SECRET|PASSWORD|API_KEY)\s*=", re.I)


class BrowserWorkerAdapter:
    """Submit scoped work to a separately deployed, credential-isolated worker."""

    def __init__(self) -> None:
        self._base_url = os.getenv("BROWSER_WORKER_URL", "").strip().rstrip("/")
        self._token = os.getenv("BROWSER_WORKER_TOKEN", "").strip()
        if not self._base_url or not self._token:
            raise BrowserExecutionError("browser_worker_configuration_missing")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def submit(self, *, task_id: str, client_id: str, target_url: str, instructions: str) -> dict[str, Any]:
        if not target_url.startswith("https://"):
            raise BrowserExecutionError("browser_target_must_use_https")
        if SECRET_PATTERN.search(instructions):
            raise BrowserExecutionError("browser_instructions_contain_secret")
        try:
            response = httpx.post(
                f"{self._base_url}/execute",
                headers=self._headers(),
                json={"task_id": task_id, "client_id": client_id, "target_url": target_url, "instructions": instructions},
                timeout=20,
            )
        except httpx.HTTPError as error:
            raise BrowserExecutionError("browser_worker_temporarily_unavailable", retryable=True) from error
        if response.status_code in {401, 403}:
            raise BrowserExecutionError("browser_worker_authorization_failed")
        if response.status_code == 429 or response.status_code >= 500:
            raise BrowserExecutionError("browser_worker_temporarily_unavailable", retryable=True)
        if response.status_code >= 400:
            raise BrowserExecutionError("browser_worker_request_rejected")
        payload = response.json()
        job_id = payload.get("job_id") if isinstance(payload, dict) else None
        if not isinstance(job_id, str) or not job_id:
            raise BrowserExecutionError("browser_worker_invalid_response", retryable=True)
        return {"job_id": job_id, "status": payload.get("status", "queued")}

    def poll(self, job_id: str) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self._base_url}/execute/{job_id}", headers=self._headers(), timeout=20)
        except httpx.HTTPError as error:
            raise BrowserExecutionError("browser_worker_temporarily_unavailable", retryable=True) from error
        if response.status_code in {401, 403}:
            raise BrowserExecutionError("browser_worker_authorization_failed")
        if response.status_code == 404:
            raise BrowserExecutionError("browser_worker_job_not_found")
        if response.status_code == 429 or response.status_code >= 500:
            raise BrowserExecutionError("browser_worker_temporarily_unavailable", retryable=True)
        if response.status_code >= 400:
            raise BrowserExecutionError("browser_worker_request_failed")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            raise BrowserExecutionError("browser_worker_invalid_response", retryable=True)
        return payload
