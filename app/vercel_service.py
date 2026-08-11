"""Replaceable Vercel project and deployment adapter.

Project discovery is read-only. Deployment is a separate explicit method used
only after Max has validated an approved website execution.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class VercelIntegrationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class VercelProject:
    project_id: str
    project_name: str
    production_url: Optional[str]
    status: str
    production_domains: tuple[str, ...] = ()
    repository_url: Optional[str] = None


class VercelAdapter:
    """Read one Vercel project using a token supplied only at runtime."""

    def __init__(self, token: Optional[str] = None) -> None:
        self._token = (token or os.getenv("VERCEL_API_TOKEN", "")).strip()
        if not self._token:
            raise VercelIntegrationError("vercel_token_missing")

    def _read_json(self, url: str) -> dict:
        request = Request(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        try:
            with urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in {401, 403}:
                raise VercelIntegrationError("vercel_authorization_failed") from error
            if error.code == 404:
                raise VercelIntegrationError("vercel_project_not_found") from error
            if error.code == 429 or error.code >= 500:
                raise VercelIntegrationError("vercel_temporarily_unavailable", retryable=True) from error
            raise VercelIntegrationError("vercel_request_failed") from error
        except (URLError, TimeoutError) as error:
            raise VercelIntegrationError("vercel_temporarily_unavailable", retryable=True) from error
        if not isinstance(body, dict):
            raise VercelIntegrationError("vercel_invalid_response", retryable=True)
        return body

    @staticmethod
    def _project(body: dict) -> VercelProject:
        production = body.get("targets", {}).get("production", {}) or {}
        aliases: list[str] = []
        if production.get("url"):
            aliases.append(str(production["url"]))
        for deployment in body.get("latestDeployments", []) or []:
            aliases.extend(str(alias) for alias in deployment.get("alias", []) or [])
        aliases.extend(str(alias) for alias in body.get("alias", []) or [])
        aliases = list(dict.fromkeys(alias for alias in aliases if alias))
        link = body.get("link") or {}
        repository_url = None
        if link.get("type") == "github" and link.get("org") and link.get("repo"):
            repository_url = f"https://github.com/{link['org']}/{link['repo']}"
        return VercelProject(
            project_id=str(body.get("id", "")),
            project_name=str(body.get("name", "")),
            production_url=aliases[0] if aliases else None,
            status="available",
            production_domains=tuple(aliases),
            repository_url=repository_url,
        )

    def get_project(self, project_id: str) -> VercelProject:
        return self._project(self._read_json(f"https://api.vercel.com/v9/projects/{project_id}"))

    def list_projects(self) -> list[VercelProject]:
        """Discover every project visible to the configured agency token."""
        projects: list[VercelProject] = []
        cursor: Optional[str] = None
        team_id = os.getenv("VERCEL_TEAM_ID", "").strip()
        for _page in range(10):
            query = {"limit": "100"}
            if team_id:
                query["teamId"] = team_id
            if cursor:
                query["until"] = cursor
            body = self._read_json(f"https://api.vercel.com/v9/projects?{urlencode(query)}")
            rows = body.get("projects", [])
            if not isinstance(rows, list):
                raise VercelIntegrationError("vercel_invalid_response", retryable=True)
            projects.extend(self._project(row) for row in rows)
            next_cursor = (body.get("pagination") or {}).get("next")
            if not next_cursor:
                break
            cursor = str(next_cursor)
        return projects

    def trigger_git_deployment(self, project_id: str, owner: str, repository: str, branch: str) -> dict:
        """Trigger a deployment for a committed, verified GitHub branch."""
        payload = {
            "name": repository,
            "project": project_id,
            "gitSource": {"type": "github", "org": owner, "repo": repository, "ref": branch},
        }
        request = Request(
            "https://api.vercel.com/v13/deployments",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode())
        except HTTPError as error:
            if error.code in {401, 403}:
                raise VercelIntegrationError("vercel_authorization_failed") from error
            if error.code == 429 or error.code >= 500:
                raise VercelIntegrationError("vercel_temporarily_unavailable", retryable=True) from error
            raise VercelIntegrationError("vercel_deployment_failed") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise VercelIntegrationError("vercel_temporarily_unavailable", retryable=True) from error
        deployment_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(deployment_id, str) or not deployment_id:
            raise VercelIntegrationError("vercel_invalid_response", retryable=True)
        return {"deployment_id": deployment_id, "url": body.get("url"), "ready_state": body.get("readyState", "queued")}

    def get_deployment(self, deployment_id: str) -> dict:
        """Read one deployment's terminal/build state without changing it."""
        if not deployment_id.strip():
            raise VercelIntegrationError("vercel_deployment_id_missing")
        body = self._read_json(f"https://api.vercel.com/v13/deployments/{deployment_id.strip()}")
        ready_state = str(body.get("readyState") or body.get("status") or "unknown").casefold()
        return {
            "deployment_id": deployment_id.strip(),
            "ready_state": ready_state,
            "url": body.get("url"),
            "error_code": (body.get("errorCode") or (body.get("error") or {}).get("code")),
            "error_message": None,
        }
