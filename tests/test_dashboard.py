"""Tests for the agency-owner client-list screen."""


def make_dashboard_client(client, business_name: str) -> str:
    response = client.post(
        "/clients",
        json={"business_name": business_name, "service_start_date": "2026-08-10"},
    )
    return response.json()["id"]


def dashboard_row(page: str, client_id: str) -> str:
    """Return only one client's row so statuses cannot leak between rows."""
    row_start = page.index(f'data-client-id="{client_id}"')
    row_end = page.index("</article>", row_start)
    return page[row_start:row_end]


def test_dashboard_shows_client_list_information() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app

    business_name = f"Dashboard Client {uuid4().hex[:8]}"
    with TestClient(app) as client:
        client_id = make_dashboard_client(client, business_name)
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    row = dashboard_row(response.text, client_id)
    assert business_name in row
    assert "Not started" in row
    assert "Aug 10, 2026" in row
    assert "Action required" in row
    assert "Submit onboarding" in row
    assert f'href="/dashboard/clients/{client_id}"' in row
    assert f'href="/dashboard/clients/{client_id}/metrics"' in row
    assert f'href="/dashboard/clients/{client_id}/health"' in row


def test_dashboard_navigation_points_to_the_client_workspace() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert 'href="/dashboard"' in response.text
    assert 'href="/docs"' in response.text
    assert 'href="/dashboard/tasks/approvals"' in response.text
    assert 'href="/dashboard/connections"' in response.text
    assert "Open a client to review intake and profile" in response.text
    assert "not built yet" not in response.text


def test_connections_dashboard_hides_secrets_and_shows_client_readiness() -> None:
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.main import app

    name = f"Connection Dashboard {uuid4().hex[:8]}"
    with TestClient(app) as client:
        client_id = make_dashboard_client(client, name)
        response = client.get("/dashboard/connections")

    assert response.status_code == 200
    assert name in response.text
    assert client_id in response.text
    assert "GitHub App" in response.text
    assert "Vercel" in response.text
    assert "Search Console" in response.text
    assert "Secrets hidden" in response.text
    assert ".pem" not in response.text


def test_browser_root_describes_the_project_without_client_data() -> None:
    """The root is a static project description, not an entrance to the workspace.

    A public deployment has no owner session, so sending the root to /dashboard
    only produced an error page. Serving the description keeps the root useful
    while every application route stays fail-closed.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Max</h1>" in response.text
    # The page must never grow a data-backed section.
    assert "made up" in response.text


def test_dashboard_keeps_each_clients_onboarding_status_separate() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_intakes import make_intake_payload

    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        submitted_client_id = make_dashboard_client(client, f"Submitted Dashboard {suffix}")
        waiting_client_id = make_dashboard_client(client, f"Waiting Dashboard {suffix}")
        client.post(
            f"/clients/{submitted_client_id}/intakes",
            json=make_intake_payload(),
        )
        response = client.get("/dashboard")

    submitted_row = dashboard_row(response.text, submitted_client_id)
    waiting_row = dashboard_row(response.text, waiting_client_id)
    assert "Submitted" in submitted_row
    assert "No owner action" in submitted_row
    assert "Not started" in waiting_row
    assert "Action required" in waiting_row


def test_dashboard_shows_profile_review_and_task_approval_actions() -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_tasks import approve, make_findings, proposal

    with TestClient(app) as client:
        client_id, findings = make_findings(client, "Dashboard Task Review")
        task = client.post(f"/clients/{client_id}/tasks", json=proposal(findings[0]["id"]))
        page = client.get("/dashboard")
        before_approval = dashboard_row(page.text, client_id)
        approve(client, task.json()["id"])
        after_approval = client.get("/dashboard")
        after_approval_row = dashboard_row(after_approval.text, client_id)

    assert "Approve task" in before_approval
    assert "Action required" in before_approval
    assert "Waiting for proposal" in after_approval_row
    assert "No owner action" in after_approval_row


def test_dashboard_escapes_saved_business_name() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app

    unsafe_name = f"Roofing <script>{uuid4().hex[:8]}</script>"
    with TestClient(app) as client:
        client_id = make_dashboard_client(client, unsafe_name)
        response = client.get("/dashboard")

    row = dashboard_row(response.text, client_id)
    assert "<script>" not in row
    assert "&lt;script&gt;" in row


def test_client_workspace_shows_original_intake_and_profile_review() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_intakes import make_intake_payload

    with TestClient(app) as client:
        client_id = make_dashboard_client(client, "Workspace Review")
        intake = client.post(f"/clients/{client_id}/intakes", json=make_intake_payload()).json()
        created = client.post(f"/dashboard/clients/{client_id}/intakes/{intake['id']}/interpret")
        intake_page = client.get(f"/dashboard/clients/{client_id}?section=intake")
        review_page = client.get(f"/dashboard/clients/{client_id}?section=review")

    assert created.status_code == 200
    assert "Original onboarding intake" in intake_page.text
    assert intake["phone_number"] in intake_page.text
    assert "Profile review" in review_page.text
    assert "Approve profile" in review_page.text
    assert "Reject with reason" in review_page.text


def test_client_workspace_approval_creates_official_profile() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_intakes import make_intake_payload

    with TestClient(app) as client:
        client_id = make_dashboard_client(client, "Workspace Approval")
        intake = client.post(f"/clients/{client_id}/intakes", json=make_intake_payload()).json()
        client.post(f"/dashboard/clients/{client_id}/intakes/{intake['id']}/interpret")
        version = client.get(f"/dashboard/clients/{client_id}?section=review")
        start = version.text.index('/profile-versions/') + len('/profile-versions/')
        version_id = version.text[start:].split('/decision', 1)[0]
        approved = client.post(
            f"/dashboard/clients/{client_id}/profile-versions/{version_id}/decision",
            data={"decision": "approve", "decision_maker": "Agency Owner"},
        )
        official = client.get(f"/dashboard/clients/{client_id}?section=official")

    assert approved.status_code == 200
    assert "Official client profile" in official.text
    assert "Agency Owner" in official.text


def test_browser_onboarding_creates_client_and_original_intake() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app

    business_name = f"Browser Onboarding {uuid4().hex[:8]}"
    data = {
        "business_name": business_name,
        "service_start_date": "2026-08-11",
        "phone_number": "555-0100",
        "email": "owner@example.com",
        "domain": "example.com",
        "google_business_profile": "https://maps.google.com/example",
        "brand_colors": "#123456, #ffffff",
        "business_hours": "Mon-Fri 8am-5pm",
        "service_areas": "Demo City, Ankeny",
        "enabled_workflows": "website, reporting",
        "asset_references": "https://files.example.com/logo.png\nhttps://files.example.com/team.jpg",
    }
    with TestClient(app) as client:
        form = client.get("/dashboard/onboarding")
        response = client.post("/dashboard/onboarding", data=data)
        saved_client = client.get("/clients").json()
        created = next(item for item in saved_client if item["business_name"] == business_name)
        overview = client.get(f"/dashboard/clients/{created['id']}")

    assert form.status_code == 200
    assert "Create client and save intake" in form.text
    assert response.status_code == 200
    assert "Original onboarding intake" in response.text
    assert business_name in response.text
    assert "#123456" in response.text
    assert "logo.png" in overview.text
    assert created["service_start_date"] == "2026-08-11"


def test_asset_references_stay_with_the_correct_client_profile() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_intakes import make_intake_payload

    with TestClient(app) as client:
        first_id = make_dashboard_client(client, "Assets First")
        second_id = make_dashboard_client(client, "Assets Second")
        first_intake = client.post(f"/clients/{first_id}/intakes", json=make_intake_payload()).json()
        client.post(
            f"/dashboard/clients/{first_id}/intakes/new",
            data={
                "phone_number": "555-1111", "email": "first@example.com", "domain": "first.example.com",
                "google_business_profile": "First GBP", "brand_colors": "blue", "business_hours": "Always",
                "service_areas": "First City", "enabled_workflows": "website",
                "asset_references": "https://files.example.com/first-logo.png",
            },
        )
        first_proposal = client.post(f"/intakes/{first_intake['id']}/interpret")
        second_page = client.get(f"/dashboard/clients/{second_id}")

    assert "https://files.example.com/first-logo.png" in first_proposal.json()["profile_data"]["asset_references"]
    assert "first-logo.png" not in second_page.text


def test_browser_onboarding_prevents_duplicate_business_names() -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app

    data = {
        "business_name": f"Duplicate Onboarding {uuid4().hex[:8]}",
        "service_start_date": "2026-08-11", "phone_number": "555-0100",
        "email": "owner@example.com", "domain": "example.com",
        "google_business_profile": "GBP", "brand_colors": "#123456",
        "business_hours": "Mon-Fri", "service_areas": "Demo City", "enabled_workflows": "website",
    }
    with TestClient(app) as client:
        client.post("/dashboard/onboarding", data=data)
        duplicate = client.post("/dashboard/onboarding", data=data)

    assert duplicate.status_code == 200
    assert "already exists" in duplicate.text


def test_release_readiness_dashboard_is_secret_free_and_actionable() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/dashboard/release-readiness")

    assert response.status_code == 200
    assert "Release readiness" in response.text
    assert "database_migrations" in response.text
    assert "Run alembic upgrade head" in response.text
    assert "auth-secret-value" not in response.text


def test_existing_client_can_save_a_new_intake_without_changing_the_first() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_intakes import make_intake_payload

    with TestClient(app) as client:
        client_id = make_dashboard_client(client, "Additional Intake")
        first = client.post(f"/clients/{client_id}/intakes", json=make_intake_payload()).json()
        form = client.get(f"/dashboard/clients/{client_id}/intakes/new")
        data = {
            "phone_number": "555-0199", "email": "new@example.com", "domain": "new.example.com",
            "google_business_profile": "Updated GBP", "brand_colors": "black, blue",
            "business_hours": "Every day", "service_areas": "Austin, Round Rock",
            "enabled_workflows": "website, reporting",
        }
        saved = client.post(f"/dashboard/clients/{client_id}/intakes/new", data=data)
        intake_page = client.get(f"/dashboard/clients/{client_id}?section=intake")
        first_saved = client.get(f"/intakes/{first['id']}")

    assert form.status_code == 200
    assert "Save new intake version" in form.text
    assert saved.status_code == 200
    assert "555-0199" in intake_page.text
    assert first_saved.json()["phone_number"] == "555-123-4567"
