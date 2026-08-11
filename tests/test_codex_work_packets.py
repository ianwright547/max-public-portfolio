"""Codex work packets are scoped, approved, and safe to repeat."""

import json
from typing import Optional
from uuid import uuid4

from fastapi.testclient import TestClient
from app import models
from app.database import SessionLocal

from app.main import app
from tests.test_tasks import approve, make_findings, proposal


def link_website(client: TestClient, client_id: str, suffix: str) -> dict:
    response = client.post(
        f"/clients/{client_id}/website-connection",
        json={
            "external_project_id": f"prj_{suffix}",
            "project_name": f"max-{suffix}",
            "production_url": f"https://{suffix}.example.com",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def link_repository(client: TestClient, client_id: str, suffix: str) -> dict:
    response = client.post(
        f"/clients/{client_id}/github-repository",
        json={
            "owner": "agency",
            "repository_name": f"client-{suffix}",
            "repository_url": f"https://github.com/agency/client-{suffix}",
            "default_branch": "main",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def packet_request(connection: dict, suffix: str, operation_key: Optional[str] = None) -> dict:
    return {
        "operation_key": operation_key or f"packet-operation-{suffix}",
        "created_by": "Agency Owner",
        "mode": "replicate",
        "repository_owner": "agency",
        "repository_name": f"client-{suffix}",
        "repository_url": f"https://github.com/agency/client-{suffix}",
        "branch": "main",
        "vercel_project_id": connection["external_project_id"],
        "domain": connection["production_url"],
        "allowed_paths": ["app/**", "public/**"],
        "publish_allowed": False,
    }


def acceptance_checks() -> list[dict[str, str]]:
    return [
        {"criterion": "requested outcome", "status": "passed", "evidence": "Result reviewed"},
        {"criterion": "allowed files", "status": "passed", "evidence": "Packet scope reviewed"},
        {"criterion": "client target", "status": "passed", "evidence": "Client and domain reviewed"},
    ]


def approved_task(client: TestClient, suffix: str) -> tuple[str, str]:
    client_id, findings = make_findings(client, suffix)
    task = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"]))
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    assert approve(client, task_id).status_code == 200
    return client_id, task_id


def test_approved_task_creates_complete_scoped_packet_without_credentials() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Complete")
        connection = link_website(client, client_id, "packet-complete")
        link_repository(client, client_id, "packet-complete")
        response = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "packet-complete"),
        )

    assert response.status_code == 201, response.text
    packet = response.json()
    assert packet["client_id"] == client_id
    assert packet["task_id"] == task_id
    assert packet["expires_at"] > packet["created_at"]
    assert packet["packet_data"]["task_summary"] == "Restore the client website"
    assert packet["packet_data"]["github"]["repository"] == "client-packet-complete"
    assert packet["packet_data"]["vercel"]["production_domain"] == "packet-complete.example.com"
    assert "skills_and_sops" in packet["packet_data"]
    assert packet["packet_data"]["local_seo_work_type"] == "website_build"
    assert "docs/knowledge/skills/local-seo/SKILL.md" in packet["packet_data"]["skills_and_sops"]
    assert "required_final_response_format" in packet["packet_data"]
    assert "credentials" in packet["packet_data"]["safety_instruction"].lower()
    assert "token" not in str(packet["packet_data"]).lower()
    assert packet["quality"]["status"] == "ready"
    assert packet["quality"]["summary"]["blocked"] == 0


def test_packet_quality_endpoint_blocks_handoff_when_acceptance_contract_is_corrupted() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Quality Gate")
        connection = link_website(client, client_id, "packet-quality-gate")
        link_repository(client, client_id, "packet-quality-gate")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "packet-quality-gate"),
        ).json()
        with SessionLocal() as database:
            saved = database.get(models.CodexWorkPacket, packet["id"])
            saved.packet_data = {**saved.packet_data, "measurement_contract": {"expected_result": ""}}
            database.commit()
        quality = client.get(f"/codex-work-packets/{packet['id']}/quality")
        handoff = client.post(
            f"/codex-work-packets/{packet['id']}/handoff",
            json={"handed_off_by": "Agency Owner"},
        )

    assert quality.status_code == 200
    assert quality.json()["status"] == "blocked"
    assert quality.json()["summary"]["blocked"] >= 1
    assert any(item["key"] == "measurement_contract" for item in quality.json()["checks"] if item["status"] == "blocked")
    assert handoff.status_code == 409
    assert "Packet quality gate blocked handoff" in handoff.json()["detail"]


def test_unapproved_task_cannot_receive_work_packet() -> None:
    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Packet Unapproved")
        task = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"])).json()
        connection = link_website(client, client_id, "packet-unapproved")
        link_repository(client, client_id, "packet-unapproved")
        response = client.post(
            f"/tasks/{task['id']}/codex-work-packet",
            json=packet_request(connection, "packet-unapproved"),
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Only an approved or ready task can receive a Codex work packet"


def test_packet_requires_matching_website_project_and_domain() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Mismatch")
        connection = link_website(client, client_id, "packet-mismatch")
        link_repository(client, client_id, "packet-mismatch")
        wrong_project = packet_request(connection, "packet-mismatch", "wrong-project")
        wrong_project["vercel_project_id"] = "prj_someone-else"
        project_response = client.post(f"/tasks/{task_id}/codex-work-packet", json=wrong_project)
        wrong_domain = packet_request(connection, "packet-mismatch", "wrong-domain")
        wrong_domain["domain"] = "someone-else.example.com"
        domain_response = client.post(f"/tasks/{task_id}/codex-work-packet", json=wrong_domain)

    assert project_response.status_code == 409
    assert project_response.json()["detail"] == "Vercel project does not match this client"
    assert domain_response.status_code == 409
    assert domain_response.json()["detail"] == "Production domain does not match this client"


def test_operation_key_is_idempotent_but_cannot_cross_tasks_or_clients() -> None:
    with TestClient(app) as client:
        first_client_id, first_task_id = approved_task(client, "Packet First")
        first_connection = link_website(client, first_client_id, "packet-first")
        link_repository(client, first_client_id, "packet-first")
        first_payload = packet_request(first_connection, "packet-first", "shared-operation-key")
        first = client.post(f"/tasks/{first_task_id}/codex-work-packet", json=first_payload)
        repeat = client.post(f"/tasks/{first_task_id}/codex-work-packet", json=first_payload)

        second_client_id, second_task_id = approved_task(client, "Packet Second")
        second_connection = link_website(client, second_client_id, "packet-second")
        link_repository(client, second_client_id, "packet-second")
        attempted_cross_client = client.post(
            f"/tasks/{second_task_id}/codex-work-packet",
            json=packet_request(second_connection, "packet-second", "shared-operation-key"),
        )
        first_list = client.get(f"/clients/{first_client_id}/codex-work-packets")
        second_list = client.get(f"/clients/{second_client_id}/codex-work-packets")

    assert first.status_code == 201
    assert repeat.status_code == 201
    assert repeat.json()["reused_existing"] is True
    assert repeat.json()["id"] == first.json()["id"]
    assert attempted_cross_client.status_code == 409
    assert attempted_cross_client.json()["detail"] == "This operation key already belongs to a different task"
    assert [packet["client_id"] for packet in first_list.json()] == [first_client_id]
    assert second_list.json() == []


def test_packet_requires_verified_website_connection() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet No Website")
        link_repository(client, client_id, "packet-no-website")
        response = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json={
                **packet_request(
                    {"external_project_id": "prj_missing", "production_url": "https://missing.example.com"},
                    "packet-no-website",
                ),
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "A verified website connection is required before creating a Codex work packet"


def test_packet_requires_matching_client_bound_github_repository() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Github")
        connection = link_website(client, client_id, "packet-github")
        missing = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "packet-github", "missing-github"),
        )
        link_repository(client, client_id, "packet-github")
        wrong_repo = packet_request(connection, "packet-github", "wrong-github")
        wrong_repo["repository_name"] = "another-client"
        mismatch = client.post(f"/tasks/{task_id}/codex-work-packet", json=wrong_repo)

    assert missing.status_code == 409
    assert missing.json()["detail"] == "A verified GitHub repository connection is required before creating a Codex work packet"
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == "GitHub repository or branch does not match this client"


def test_github_repository_verification_records_success_and_mismatch(monkeypatch) -> None:
    from app.github_service import GitHubRepository

    class MatchingAdapter:
        def get_repository(self, owner, repository_name):
            return GitHubRepository(
                repository_id="123",
                owner=owner,
                name=repository_name,
                html_url=f"https://github.com/{owner}/{repository_name}",
                default_branch="main",
                private=True,
            )

    with TestClient(app) as client:
        client_id, _task_id = approved_task(client, "Packet Github Verify")
        link_repository(client, client_id, "packet-github-verify")
        monkeypatch.setattr("app.routes.github_repositories.GitHubAppAdapter", MatchingAdapter)
        success = client.post(f"/clients/{client_id}/github-repository/verify")

        class MismatchedAdapter(MatchingAdapter):
            def get_repository(self, owner, repository_name):
                return GitHubRepository(
                    repository_id="123",
                    owner="other-agency",
                    name=repository_name,
                    html_url="https://github.com/other-agency/another-client",
                    default_branch="trunk",
                    private=True,
                )

        monkeypatch.setattr("app.routes.github_repositories.GitHubAppAdapter", MismatchedAdapter)
        mismatch = client.post(f"/clients/{client_id}/github-repository/verify")
        saved = client.get(f"/clients/{client_id}/github-repository")

    assert success.json()["connection_status"] == "connected"
    assert success.json()["issues"] == []
    assert mismatch.json()["connection_status"] == "mismatch"
    assert set(mismatch.json()["issues"]) == {
        "github_owner_mismatch",
        "github_repository_url_mismatch",
        "github_default_branch_mismatch",
    }
    assert saved.json()["connection_status"] == "mismatch"
    assert saved.json()["last_checked_at"] is not None
    assert saved.json()["last_verified_at"] is not None


def test_packet_routes_blog_work_to_human_writing_and_content_brief_rules() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Blog Routing")
        connection = link_website(client, client_id, "packet-blog-routing")
        link_repository(client, client_id, "packet-blog-routing")
        request = packet_request(connection, "packet-blog-routing", "blog-routing-key")
        request["seo_work_type"] = "blog"
        created = client.post(f"/tasks/{task_id}/codex-work-packet", json=request)

    assert created.status_code == 201
    packet = created.json()["packet_data"]
    assert packet["local_seo_work_type"] == "blog"
    assert "docs/knowledge/sops/universal_human_writing_sop.md" in packet["skills_and_sops"]
    assert "customer need" in packet["local_seo_guidance"]


def test_blog_result_requires_and_records_human_content_review() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Blog Review")
        connection = link_website(client, client_id, "packet-blog-review")
        link_repository(client, client_id, "packet-blog-review")
        request = packet_request(connection, "packet-blog-review", "blog-review-key")
        request["seo_work_type"] = "blog"
        packet = client.post(f"/tasks/{task_id}/codex-work-packet", json=request).json()
        packet_id = packet["id"]
        assert client.post(
            f"/codex-work-packets/{packet_id}/handoff",
            json={"handed_off_by": "Agency Owner"},
        ).status_code == 200
        result = client.post(
            f"/codex-work-packets/{packet_id}/result",
            json={
                "operation_key": "blog-review-result-key",
                "outcome": "completed",
                "submitted_by": "Codex",
                "summary": "Drafted the scoped article.",
                "changed_files": ["app/article.md"],
                "tests": [{"name": "content lint", "status": "passed"}],
                "evidence": ["Draft file app/article.md"],
                "verification_data": {"acceptance_checks": acceptance_checks()},
                "blockers": [],
                "actual_cost": 0,
            },
        )
        before_review = client.get(f"/codex-work-packets/{packet_id}/content-review")
        execution_id = result.json()["execution"]["id"]
        verification_payload = {
            "decision_key": "blog-review-before-content-review",
            "outcome": "verified",
            "reviewer": "Agency Owner",
            "explanation": "The scoped content output matches the approved request.",
            "review_evidence": ["Compared the packet, execution, and content review"],
            "correct_client_confirmed": True,
            "approved_task_followed": True,
            "output_exists": True,
            "result_matches_requested_outcome": True,
            "no_unexpected_changes": True,
        }
        blocked_verification = client.post(
            f"/executions/{execution_id}/verifications",
            json=verification_payload,
        )
        rejected = client.post(
            f"/codex-work-packets/{packet_id}/content-review",
            json={
                "reviewer": "Agency Owner",
                "status": "approved",
                "checklist": {key: key == "facts_supported" for key in (
                    "facts_supported", "intent_match", "human_writing_pass",
                    "no_doorway_or_unsupported_claims", "links_and_cta_checked",
                )},
                "notes": "Human writing and unsupported-claim checks are incomplete.",
            },
        )
        approved_review = client.post(
            f"/codex-work-packets/{packet_id}/content-review",
            json={
                "reviewer": "Agency Owner",
                "status": "approved",
                "checklist": {key: True for key in (
                    "facts_supported", "intent_match", "human_writing_pass",
                    "no_doorway_or_unsupported_claims", "links_and_cta_checked",
                )},
                "notes": "Reviewed against the approved facts and human-writing SOP.",
            },
        )
        saved_review = client.get(f"/codex-work-packets/{packet_id}/content-review")
        verified = client.post(
            f"/executions/{execution_id}/verifications",
            json={**verification_payload, "decision_key": "blog-review-after-content-review"},
        )

    assert result.status_code == 200
    assert before_review.status_code == 404
    assert blocked_verification.status_code == 409
    assert "content_review_approved" in blocked_verification.json()["detail"]
    assert rejected.status_code == 409
    assert approved_review.status_code == 200
    assert saved_review.json()["status"] == "approved"
    assert verified.status_code == 201


def test_specialized_seo_contracts_are_persisted_and_rendered() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Specialized Contracts")
        connection = link_website(client, client_id, "packet-specialized-contracts")
        link_repository(client, client_id, "packet-specialized-contracts")
        request = packet_request(connection, "packet-specialized-contracts", "specialized-contract-key")
        request["seo_work_type"] = "local_page"
        created = client.post(f"/tasks/{task_id}/codex-work-packet", json=request)
        handoff = client.get(f"/codex-work-packets/{created.json()['id']}/handoff")

    assert created.status_code == 201
    contract = created.json()["packet_data"]["specialized_acceptance_contract"]
    assert "page_url_or_path" in contract["result_keys"]
    assert "doorway" in contract["guidance"].lower()
    brief = created.json()["packet_data"]["content_brief"]
    assert brief["content_type"] == "local_page"
    assert brief["approved_facts_source"]
    assert brief["prohibited_claims"]
    assert "Specialized acceptance contract" in handoff.json()["handoff_text"]
    assert "Evidence-backed content brief" in handoff.json()["handoff_text"]
    assert "verification_data" in handoff.json()["handoff_text"]


def test_completed_technical_seo_result_requires_passing_structured_checks() -> None:
    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Packet Technical Contract")
        proposed = client.post(
            f"/clients/{client_id}/tasks",
            json={
                **proposal(findings[0]["id"]),
                "title": "Fix technical SEO canonical",
                "requested_outcome": "Fix canonical and indexability directives.",
            },
        )
        task_id = proposed.json()["id"]
        assert approve(client, task_id).status_code == 200
        connection = link_website(client, client_id, "packet-technical-contract")
        link_repository(client, client_id, "packet-technical-contract")
        request = packet_request(connection, "packet-technical-contract", "technical-contract-key")
        request["seo_work_type"] = "technical_seo"
        packet = client.post(f"/tasks/{task_id}/codex-work-packet", json=request).json()
        client.post(f"/codex-work-packets/{packet['id']}/handoff", json={"handed_off_by": "Owner"})
        base = {
            "operation_key": "technical-contract-result",
            "outcome": "completed",
            "submitted_by": "Owner",
            "summary": "Fixed canonical directives.",
                "changed_files": ["public/robots.txt"],
                "tests": [{"name": "build", "status": "passed"}],
                "evidence": ["Canonical response inspected"],
            }
        missing = client.post(f"/codex-work-packets/{packet['id']}/result", json=base)
        failed = client.post(
            f"/codex-work-packets/{packet['id']}/result",
            json={**base, "verification_data": {"technical_checks": {"canonical": {"status": "failed"}}}},
        )
        valid = client.post(
            f"/codex-work-packets/{packet['id']}/result",
            json={
                **base,
                "verification_data": {
                    "technical_checks": {"canonical": {"status": "passed", "evidence": "https://example.com/"}},
                    "acceptance_checks": acceptance_checks(),
                },
            },
        )

    assert missing.status_code == 422
    assert "technical_checks" in missing.json()["detail"]
    assert failed.status_code == 422
    assert "failed" in failed.json()["detail"]
    assert valid.status_code == 200, valid.text


def test_generic_completed_result_requires_evidence_backed_acceptance_checks() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Acceptance Checklist")
        connection = link_website(client, client_id, "packet-acceptance-checklist")
        link_repository(client, client_id, "packet-acceptance-checklist")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "packet-acceptance-checklist", "acceptance-checklist-key"),
        ).json()
        client.post(f"/codex-work-packets/{packet['id']}/handoff", json={"handed_off_by": "Owner"})
        result = client.post(
            f"/codex-work-packets/{packet['id']}/result",
            json={
                "operation_key": "acceptance-checklist-result",
                "outcome": "completed",
                "submitted_by": "Codex",
                "summary": "Completed the scoped work.",
                "changed_files": ["app/page.py"],
                "evidence": ["Changed file reviewed"],
            },
        )

    assert result.status_code == 422
    assert "acceptance_checks" in result.json()["detail"]


def test_completed_result_rejects_duplicate_acceptance_checks() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Duplicate Acceptance")
        connection = link_website(client, client_id, "packet-duplicate-acceptance")
        link_repository(client, client_id, "packet-duplicate-acceptance")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "packet-duplicate-acceptance", "duplicate-acceptance-key"),
        ).json()
        client.post(f"/codex-work-packets/{packet['id']}/handoff", json={"handed_off_by": "Owner"})
        checks = acceptance_checks()
        checks[1] = {**checks[0]}
        result = client.post(
            f"/codex-work-packets/{packet['id']}/result",
            json={
                "operation_key": "duplicate-acceptance-result",
                "outcome": "completed",
                "submitted_by": "Codex",
                "summary": "Completed the scoped work.",
                "changed_files": ["app/page.py"],
                "evidence": ["Changed file reviewed"],
                "verification_data": {"acceptance_checks": checks},
            },
        )

    assert result.status_code == 422
    assert "cannot repeat" in result.json()["detail"]


def test_packet_cannot_allow_publishing_until_task_is_ready() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Packet Publishing Gate")
        connection = link_website(client, client_id, "packet-publishing-gate")
        link_repository(client, client_id, "packet-publishing-gate")
        request = packet_request(connection, "packet-publishing-gate", "publishing-gate-key")
        request["publish_allowed"] = True
        blocked = client.post(f"/tasks/{task_id}/codex-work-packet", json=request)
        ready = client.post(
            f"/tasks/{task_id}/status", json={"target_status": "ready", "changed_by": "Agency Owner"}
        )
        allowed = client.post(f"/tasks/{task_id}/codex-work-packet", json=request)

    assert blocked.status_code == 409
    assert "requires a ready task" in blocked.json()["detail"]
    assert ready.status_code == 200
    assert allowed.status_code == 201
    assert allowed.json()["publishing_allowed"] is True


def test_connected_packet_handoff_and_completed_result_create_real_execution() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Codex Lifecycle")
        link_website(client, client_id, "codex-lifecycle")
        link_repository(client, client_id, "codex-lifecycle")
        prepared = client.post(
            f"/tasks/{task_id}/connected-codex-work-packet",
            json={
                "operation_key": "connected-codex-lifecycle",
                "created_by": "Agency Owner",
                "mode": "repair",
            },
        )
        packet_id = prepared.json()["id"]
        preview = client.get(f"/codex-work-packets/{packet_id}/handoff")
        handed_off = client.post(
            f"/codex-work-packets/{packet_id}/handoff",
            json={"handed_off_by": "Agency Owner"},
        )
        running_task = client.get(f"/tasks/{task_id}")
        result_payload = {
            "operation_key": "codex-result-lifecycle",
            "outcome": "completed",
            "submitted_by": "Agency Owner",
            "summary": "Repaired the approved client website issue.",
            "changed_files": ["app/page.py", "public/robots.txt"],
            "tests": [{"name": "site build", "status": "passed", "detail": "Build succeeded"}],
            "commit_shas": ["abc123"],
            "deployment_url": "https://codex-lifecycle.example.com",
            "evidence": ["Production URL returned HTTP 200"],
            "verification_data": {"acceptance_checks": acceptance_checks()},
            "actual_cost": 0,
        }
        result = client.post(f"/codex-work-packets/{packet_id}/result", json=result_payload)
        repeated = client.post(f"/codex-work-packets/{packet_id}/result", json=result_payload)
        execution_id = result.json()["execution"]["id"]
        verified = client.post(
            f"/executions/{execution_id}/verifications",
            json={
                "decision_key": "verify-codex-result-lifecycle",
                "outcome": "verified",
                "reviewer": "Agency Owner",
                "explanation": "Compared the approved request, files, passing build, and production evidence.",
                "review_evidence": ["Build passed", "Production URL was checked"],
                "correct_client_confirmed": True,
                "approved_task_followed": True,
                "output_exists": True,
                "result_matches_requested_outcome": True,
                "no_unexpected_changes": True,
            },
        )
        completed_task = client.get(f"/tasks/{task_id}")

    assert prepared.status_code == 201, prepared.text
    assert prepared.json()["repository_name"] == "client-codex-lifecycle"
    assert "# Max Codex Fulfillment Handoff" in preview.json()["handoff_text"]
    assert "exact requested outcome" not in preview.json()["handoff_text"].casefold()
    assert handed_off.json()["packet"]["status"] == "handed_off"
    assert handed_off.json()["packet"]["handed_off_by"] == "Agency Owner"
    assert running_task.json()["status"] == "running"
    assert result.status_code == 200, result.text
    assert result.json()["packet"]["status"] == "completed"
    assert result.json()["execution"]["evidence"]["executor"] == "codex_handoff"
    assert result.json()["execution"]["evidence"]["simulated"] is False
    assert result.json()["execution"]["simulated_changed_files"] == ["app/page.py", "public/robots.txt"]
    assert result.json()["packet"]["result_execution_id"] == result.json()["execution"]["id"]
    assert verified.status_code == 201, verified.text
    assert verified.json()["outcome"] == "verified"
    assert completed_task.json()["status"] == "verified"
    assert repeated.json()["reused_existing"] is True


def test_codex_result_requires_handoff_and_enforces_packet_scope() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Codex Scope")
        connection = link_website(client, client_id, "codex-scope")
        link_repository(client, client_id, "codex-scope")
        packet = client.post(
            f"/tasks/{task_id}/codex-work-packet",
            json=packet_request(connection, "codex-scope", "codex-scope-packet"),
        ).json()
        payload = {
            "operation_key": "codex-scope-result",
            "outcome": "completed",
            "submitted_by": "Agency Owner",
            "summary": "Completed work.",
            "changed_files": ["private/outside.txt"],
            "tests": [],
        }
        before_handoff = client.post(f"/codex-work-packets/{packet['id']}/result", json=payload)
        client.post(
            f"/codex-work-packets/{packet['id']}/handoff",
            json={"handed_off_by": "Agency Owner"},
        )
        outside_scope = client.post(f"/codex-work-packets/{packet['id']}/result", json=payload)

    assert before_handoff.status_code == 409
    assert "before submitting" in before_handoff.json()["detail"]
    assert outside_scope.status_code == 422
    assert "outside the packet scope" in outside_scope.json()["detail"]


def test_blocked_codex_result_requires_and_preserves_blocker() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Codex Blocked")
        link_website(client, client_id, "codex-blocked")
        link_repository(client, client_id, "codex-blocked")
        packet = client.post(
            f"/tasks/{task_id}/connected-codex-work-packet",
            json={"operation_key": "codex-blocked-packet", "created_by": "Owner"},
        ).json()
        client.post(f"/codex-work-packets/{packet['id']}/handoff", json={"handed_off_by": "Owner"})
        missing = client.post(
            f"/codex-work-packets/{packet['id']}/result",
            json={
                "operation_key": "codex-blocked-result",
                "outcome": "blocked",
                "submitted_by": "Owner",
                "summary": "Could not find the expected source files.",
            },
        )
        saved = client.post(
            f"/codex-work-packets/{packet['id']}/result",
            json={
                "operation_key": "codex-blocked-result",
                "outcome": "blocked",
                "submitted_by": "Owner",
                "summary": "Could not find the expected source files.",
                "blockers": ["The connected repository does not contain the deployed website source."],
            },
        )
        task = client.get(f"/tasks/{task_id}")

    assert missing.status_code == 422
    assert "requires at least one blocker" in missing.json()["detail"]
    assert saved.status_code == 200, saved.text
    assert saved.json()["execution"]["status"] == "blocked"
    assert "does not contain" in saved.json()["execution"]["error_message"]
    assert task.json()["status"] == "blocked"


def test_approval_auto_prepares_eligible_connected_codex_packet_without_starting_work() -> None:
    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Auto Packet")
        proposed = client.post(
            f"/clients/{client_id}/tasks",
            json={
                **proposal(findings[0]["id"]),
                "title": "Repair technical SEO sitemap",
                "requested_outcome": "Repair the website sitemap and canonical configuration.",
            },
        )
        task_id = proposed.json()["id"]
        link_website(client, client_id, "auto-packet")
        link_repository(client, client_id, "auto-packet")
        approved = approve(client, task_id)
        packets = client.get(f"/clients/{client_id}/codex-work-packets").json()
        saved_task = client.get(f"/tasks/{task_id}").json()

    assert approved.status_code == 200
    assert len(packets) == 1
    assert packets[0]["operation_key"] == f"approved-task-{task_id}"
    assert packets[0]["packet_data"]["local_seo_work_type"] == "technical_seo"
    assert packets[0]["status"] == "generated"
    assert saved_task["status"] == "approved"


def test_fulfillment_dashboard_exposes_copyable_handoff_and_result_form() -> None:
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, "Codex Dashboard")
        link_website(client, client_id, "codex-dashboard")
        link_repository(client, client_id, "codex-dashboard")
        packet = client.post(
            f"/tasks/{task_id}/connected-codex-work-packet",
            json={"operation_key": "codex-dashboard-packet", "created_by": "Owner"},
        ).json()
        queue = client.get("/dashboard/fulfillment")
        detail = client.get(f"/dashboard/codex-work-packets/{packet['id']}")
        handoff = client.post(
            f"/dashboard/codex-work-packets/{packet['id']}/handoff",
            data={"handed_off_by": "Owner"},
            follow_redirects=False,
        )
        after_handoff = client.get(f"/dashboard/codex-work-packets/{packet['id']}")

    assert queue.status_code == 200
    assert "Codex handoff queue" in queue.text
    assert packet["id"] in queue.text
    assert "Copyable Codex prompt" in detail.text
    assert "Mark handed off to Codex" in detail.text
    assert handoff.status_code == 303
    assert "Return Codex evidence" in after_handoff.text


def test_cleared_slack_channel_can_handoff_packet_and_record_codex_result(monkeypatch) -> None:
    from sqlalchemy import select

    from app import models
    from app.database import SessionLocal
    from tests.test_slack import FakeSlackAdapter, connect_fake_slack, post_signed_slack_event

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    with TestClient(app) as client:
        client_id, task_id = approved_task(client, f"Codex Slack {uuid4().hex[:6]}")
        link_website(client, client_id, f"codex-slack-{uuid4().hex[:6]}")
        # Use the website suffix saved above when creating the matching repository.
        website = client.get(f"/clients/{client_id}/website-connection").json()
        suffix = website["project_name"].removeprefix("max-")
        link_repository(client, client_id, suffix)
        packet = client.post(
            f"/tasks/{task_id}/connected-codex-work-packet",
            json={"operation_key": f"codex-slack-packet-{uuid4().hex[:8]}", "created_by": "Owner"},
        ).json()
        channel = client.post(f"/clients/{client_id}/slack-channel").json()["connection"]["channel_id"]

        def mention(text: str):
            return post_signed_slack_event(
                client,
                {
                    "type": "event_callback",
                    "team_id": adapter.workspace.id,
                    "event_id": f"Ev_codex_{uuid4().hex}",
                    "event": {
                        "type": "app_mention",
                        "user": "U_CHANNEL_MEMBER",
                        "channel": channel,
                        "text": f"<@U_BOT> {text}",
                    },
                },
            )

        handed_off = mention(f"handoff codex packet {packet['id']}")
        payload = {
            "operation_key": f"codex-slack-result-{uuid4().hex[:8]}",
            "outcome": "completed",
            "submitted_by": "Channel member",
            "summary": "Completed the scoped website repair.",
            "changed_files": ["app/slack-repair.py"],
            "tests": [{"name": "build", "status": "passed"}],
            "evidence": ["Build passed"],
            "verification_data": {"acceptance_checks": acceptance_checks()},
        }
        recorded = mention(f"record codex result {packet['id']} {json.dumps(payload)}")
        with SessionLocal() as database:
            execution = database.scalar(
                select(models.FulfillmentExecution).where(
                    models.FulfillmentExecution.task_id == task_id,
                    models.FulfillmentExecution.evidence["executor"].as_string() == "codex_handoff",
                )
            )
            saved_task = database.get(models.Task, task_id)

    assert handed_off.status_code == 200
    assert recorded.status_code == 200
    assert "is now handed off" in adapter.messages[-2]["text"]
    assert "Recorded Codex result `completed`" in adapter.messages[-1]["text"]
    assert execution is not None
    assert saved_task.status == "completed"
