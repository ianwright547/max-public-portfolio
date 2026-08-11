"""GitHub App adapter used to verify mappings and commit approved website files.

Write operations are exposed separately from discovery and must be called only
after Max has validated an approved task and scoped work packet.
"""

import os
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import httpx


class GitHubIntegrationError(RuntimeError):
    """A safe provider error code that contains no credentials."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class GitHubRepository:
    repository_id: str
    owner: str
    name: str
    html_url: str
    default_branch: str
    private: bool


class GitHubAppAdapter:
    """Use an installation token to read a repository's public metadata."""

    def __init__(
        self,
        app_id: Optional[str] = None,
        private_key: Optional[str] = None,
        installation_id: Optional[str] = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._app_id = (app_id or os.getenv("GITHUB_APP_ID", "")).strip()
        raw_key = private_key if private_key is not None else os.getenv("GITHUB_APP_PRIVATE_KEY", "")
        self._private_key = raw_key.replace("\\n", "\n").strip()
        self._installation_id = (installation_id or os.getenv("GITHUB_APP_INSTALLATION_ID", "")).strip()
        self._timeout_seconds = timeout_seconds
        if not self._app_id or not self._private_key or not self._installation_id:
            raise GitHubIntegrationError("github_app_configuration_missing")

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _app_jwt(self) -> str:
        try:
            import jwt
        except ImportError as error:
            raise GitHubIntegrationError("github_jwt_dependency_missing") from error
        now = datetime.now(timezone.utc)
        try:
            return str(
                jwt.encode(
                    {
                        "iat": int((now - timedelta(seconds=30)).timestamp()),
                        "exp": int((now + timedelta(minutes=9)).timestamp()),
                        "iss": self._app_id,
                    },
                    self._private_key,
                    algorithm="RS256",
                )
            )
        except Exception as error:
            # PyJWT/cryptography exception classes vary by installed version.
            # Keep the exact private-key parsing details out of logs and APIs.
            raise GitHubIntegrationError("github_private_key_invalid") from error

    def _installation_token(self) -> str:
        try:
            response = httpx.post(
                f"https://api.github.com/app/installations/{self._installation_id}/access_tokens",
                headers=self._headers(self._app_jwt()),
                timeout=self._timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise GitHubIntegrationError("github_temporarily_unavailable", retryable=True) from error
        self._raise_for_response(response)
        token = str(response.json().get("token", ""))
        if not token:
            raise GitHubIntegrationError("github_invalid_response", retryable=True)
        return token

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in {401, 403}:
            raise GitHubIntegrationError("github_authorization_failed")
        if response.status_code == 404:
            raise GitHubIntegrationError("github_repository_not_found")
        if response.status_code == 429 or response.status_code >= 500:
            raise GitHubIntegrationError("github_temporarily_unavailable", retryable=True)
        raise GitHubIntegrationError("github_request_failed")

    def get_repository(self, owner: str, repository_name: str) -> GitHubRepository:
        if not owner.strip() or not repository_name.strip():
            raise GitHubIntegrationError("github_repository_reference_invalid")
        try:
            response = httpx.get(
                f"https://api.github.com/repos/{owner}/{repository_name}",
                headers=self._headers(self._installation_token()),
                timeout=self._timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise GitHubIntegrationError("github_temporarily_unavailable", retryable=True) from error
        self._raise_for_response(response)
        body = response.json()
        owner_data = body.get("owner") or {}
        repo_owner = str(owner_data.get("login", ""))
        repo_name = str(body.get("name", ""))
        repository_id = str(body.get("id", ""))
        url = str(body.get("html_url", ""))
        branch = str(body.get("default_branch", ""))
        if not all((repo_owner, repo_name, repository_id, url, branch)):
            raise GitHubIntegrationError("github_invalid_response", retryable=True)
        return GitHubRepository(
            repository_id=repository_id,
            owner=repo_owner,
            name=repo_name,
            html_url=url,
            default_branch=branch,
            private=bool(body.get("private", False)),
        )

    @staticmethod
    def _repository(body: dict) -> GitHubRepository:
        owner = body.get("owner") or {}
        values = {
            "repository_id": str(body.get("id", "")),
            "owner": str(owner.get("login", "")),
            "name": str(body.get("name", "")),
            "html_url": str(body.get("html_url", "")),
            "default_branch": str(body.get("default_branch", "")),
        }
        if not all(values.values()):
            raise GitHubIntegrationError("github_invalid_response", retryable=True)
        return GitHubRepository(**values, private=bool(body.get("private", False)))

    def list_repositories(self) -> list[GitHubRepository]:
        """Discover repositories granted to the configured GitHub App installation."""
        token = self._installation_token()
        repositories: list[GitHubRepository] = []
        for page in range(1, 11):
            try:
                response = httpx.get(
                    "https://api.github.com/installation/repositories",
                    params={"per_page": 100, "page": page},
                    headers=self._headers(token),
                    timeout=self._timeout_seconds,
                )
            except httpx.HTTPError as error:
                raise GitHubIntegrationError("github_temporarily_unavailable", retryable=True) from error
            self._raise_for_response(response)
            rows = response.json().get("repositories", [])
            if not isinstance(rows, list):
                raise GitHubIntegrationError("github_invalid_response", retryable=True)
            repositories.extend(self._repository(row) for row in rows)
            if len(rows) < 100:
                break
        return repositories

    def commit_files(
        self,
        owner: str,
        repository_name: str,
        branch: str,
        files: list[dict[str, str]],
        commit_message: str,
    ) -> dict[str, object]:
        """Write only the supplied files to the already verified branch."""
        if not owner.strip() or not repository_name.strip() or not branch.strip():
            raise GitHubIntegrationError("github_write_reference_invalid")
        token = self._installation_token()
        headers = self._headers(token)
        base_url = f"https://api.github.com/repos/{owner}/{repository_name}"
        try:
            ref_response = httpx.get(
                f"{base_url}/git/ref/heads/{branch}", headers=headers, timeout=self._timeout_seconds
            )
        except httpx.HTTPError as error:
            raise GitHubIntegrationError("github_temporarily_unavailable", retryable=True) from error
        self._raise_for_response(ref_response)
        base_sha = str((ref_response.json().get("object") or {}).get("sha", ""))
        if not base_sha:
            raise GitHubIntegrationError("github_invalid_response", retryable=True)

        changed_paths: list[str] = []
        commit_shas: list[str] = []
        for item in files:
            path = item["path"]
            encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
            try:
                existing = httpx.get(
                    f"{base_url}/contents/{encoded_path}",
                    params={"ref": branch},
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
                existing_sha = str(existing.json().get("sha", "")) if existing.status_code == 200 else None
                payload = {
                    "message": commit_message,
                    "content": base64.b64encode(item["content"].encode()).decode(),
                    "branch": branch,
                }
                if existing_sha:
                    payload["sha"] = existing_sha
                response = httpx.put(
                    f"{base_url}/contents/{encoded_path}",
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except httpx.HTTPError as error:
                raise GitHubIntegrationError("github_temporarily_unavailable", retryable=True) from error
            self._raise_for_response(response)
            body = response.json()
            commit_sha = str((body.get("commit") or {}).get("sha", ""))
            if not commit_sha:
                raise GitHubIntegrationError("github_invalid_response", retryable=True)
            changed_paths.append(path)
            commit_shas.append(commit_sha)
        return {"branch": branch, "changed_paths": changed_paths, "commit_shas": commit_shas}

    def revert_commit(
        self,
        owner: str,
        repository_name: str,
        commit_sha: str,
        branch: str,
    ) -> dict[str, object]:
        """Create a provider-native revert commit for one previously recorded change."""
        if not owner.strip() or not repository_name.strip() or not commit_sha.strip() or not branch.strip():
            raise GitHubIntegrationError("github_revert_reference_invalid")
        token = self._installation_token()
        try:
            response = httpx.post(
                f"https://api.github.com/repos/{owner}/{repository_name}/commits/{commit_sha}/revert",
                headers=self._headers(token),
                json={"branch": branch},
                timeout=self._timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise GitHubIntegrationError("github_temporarily_unavailable", retryable=True) from error
        self._raise_for_response(response)
        body = response.json()
        revert_sha = str((body.get("commit") or {}).get("sha", ""))
        if not revert_sha:
            raise GitHubIntegrationError("github_invalid_response", retryable=True)
        return {"reverted_commit_sha": commit_sha, "rollback_commit_sha": revert_sha, "branch": branch}
