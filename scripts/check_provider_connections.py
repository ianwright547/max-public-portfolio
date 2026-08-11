"""Verify configured GitHub, Vercel, and Google Business access read-only.

The command checks provider identity and configured target mappings without
printing credentials. It performs no repository, deployment, or GBP writes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.github_service import GitHubAppAdapter, GitHubIntegrationError
from app.google_business_profile_service import GoogleBusinessProfileAdapter, GoogleBusinessProfileIntegrationError
from app.vercel_service import VercelAdapter, VercelIntegrationError


def main() -> int:
    expected_owner = os.getenv("GITHUB_OWNER", "").strip()
    expected_repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    expected_project = os.getenv("VERCEL_PROJECT_ID", "").strip()
    account_id = os.getenv("GBP_ACCOUNT_ID", "").strip()
    location_id = os.getenv("GBP_LOCATION_ID", "").strip()
    if not expected_owner or not expected_repository:
        print("Provider verification failed: github_repository_mapping_missing", file=sys.stderr)
        return 1
    if not expected_project:
        print("Provider verification failed: vercel_project_mapping_missing", file=sys.stderr)
        return 1
    if not account_id or not location_id:
        print("Provider verification failed: gbp_location_mapping_missing", file=sys.stderr)
        return 1

    try:
        repository = GitHubAppAdapter().get_repository(expected_owner, expected_repository)
        if repository.owner.casefold() != expected_owner.casefold() or repository.name.casefold() != expected_repository.casefold():
            print("Provider verification failed: github_repository_mismatch", file=sys.stderr)
            return 1
        project = VercelAdapter().get_project(expected_project)
        if project.project_id != expected_project:
            print("Provider verification failed: vercel_project_mismatch", file=sys.stderr)
            return 1
        if not project.production_url:
            print("Provider verification failed: vercel_production_domain_missing", file=sys.stderr)
            return 1
        inspection = GoogleBusinessProfileAdapter().inspect_location(account_id, location_id)
    except GitHubIntegrationError as error:
        print(f"Provider verification failed: {error.code}", file=sys.stderr)
        return 1
    except VercelIntegrationError as error:
        print(f"Provider verification failed: {error.code}", file=sys.stderr)
        return 1
    except GoogleBusinessProfileIntegrationError as error:
        print(f"Provider verification failed: {error.code}", file=sys.stderr)
        return 1
    except Exception:
        print("Provider verification failed: provider_probe_failed", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "verified",
                "github": {
                    "owner": repository.owner,
                    "repository": repository.name,
                    "default_branch": repository.default_branch,
                    "private": repository.private,
                },
                "vercel": {
                    "project_id": project.project_id,
                    "project_name": project.project_name,
                    "production_domain_present": bool(project.production_url),
                },
                "google_business_profile": {
                    "location_id": inspection.location_id,
                    "location_name_present": bool(inspection.location_name),
                    "review_count_present": inspection.review_count is not None,
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
