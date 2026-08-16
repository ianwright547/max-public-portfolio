"""Simple and in-depth client updates stay evidence-backed and actionable."""

from datetime import date
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app import client_update_service, models
from app.database import SessionLocal


def _client(api, label: str) -> str:
    response = api.post(
        "/clients",
        json={"business_name": f"{label} {uuid4().hex[:8]}", "service_start_date": date.today().isoformat()},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_simple_update_uses_saved_data_without_live_refresh(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(
        client_update_service,
        "probe_website",
        lambda _url: (_ for _ in ()).throw(AssertionError("simple mode must not crawl")),
    )
    with TestClient(app) as api:
        client_id = _client(api, "Simple Update")
        with SessionLocal() as database:
            client = database.get(models.Client, client_id)
            report = client_update_service.generate_portfolio_update(
                database, mode="simple", client=client
            )
            text = client_update_service.render_slack_update(report)

    assert report.mode == "simple"
    assert report.clients[0].sources == ["Saved Max records (no live refresh requested)"]
    assert "Simple saved-data update" in text
    assert "30 days" not in text


def test_portfolio_update_discloses_the_active_client_cap(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(client_update_service, "MAX_PORTFOLIO_CLIENTS", 1)
    with TestClient(app) as api:
        _client(api, "Capped Portfolio One")
        _client(api, "Capped Portfolio Two")
        with SessionLocal() as database:
            report = client_update_service.generate_portfolio_update(database, mode="simple")

    assert len(report.clients) == 1
    assert report.portfolio_notes
    assert "showing 1 of" in report.portfolio_notes[0]


def test_in_depth_update_reports_fresh_gaps_90_day_actions_and_access_needs(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routes import website_metrics

    monkeypatch.setattr(
        website_metrics,
        "sync_metrics",
        lambda _request, _database: {
            "snapshots": [],
            "unmatched_tracker_sites": ["unmatched.example"],
            "reused_existing": False,
        },
    )
    monkeypatch.setattr(
        client_update_service,
        "probe_website",
        lambda _url: client_update_service.WebsiteEvidence(
            url="https://shop.example",
            final_url="https://shop.example/",
            status_code=200,
            title="Shop",
            h1_count=0,
            has_viewport=True,
            internal_link_count=1,
            image_count=3,
            images_missing_alt=2,
            robots_status=404,
            sitemap_status=404,
            audited_page_count=3,
            pages_missing_title=1,
            pages_missing_description=3,
            pages_without_one_h1=2,
            duplicate_title_count=1,
        ),
    )
    with TestClient(app) as api:
        client_id = _client(api, "Deep Update")
        with SessionLocal() as database:
            client = database.get(models.Client, client_id)
            report = client_update_service.generate_portfolio_update(
                database, mode="in_depth", client=client
            )
            update = report.clients[0]
            text = client_update_service.render_slack_update(report)
            persisted = list(
                database.scalars(
                    select(models.Finding).where(models.Finding.client_id == client_id)
                )
            )

    assert any("title length" in gap for gap in update.gaps)
    assert any("sitemap.xml" in gap for gap in update.gaps)
    assert any("Search Console" in blocker for blocker in update.blockers)
    assert any("Google Business Profile" in blocker for blocker in update.blockers)
    assert any("Connect the exact Search Console" in need for need in update.needs)
    assert update.plan_30 and update.plan_60 and update.plan_90
    assert "Next 0–30 days" in text
    assert "Days 31–60" in text
    assert "Days 61–90" in text
    assert "Could not verify" in text
    assert "Needed to continue" in text
    assert update.persisted_finding_ids
    assert persisted
    assert all(item.source == "in_depth_audit" for item in persisted)
    assert all(item.status == "open" for item in persisted)
    assert update.structured_evidence["website"]["audited_page_count"] == 3


def test_broken_internal_links_become_a_tangible_30_day_action() -> None:
    update = client_update_service.ClientUpdate("client-1", "Broken Links", "in_depth", "active")
    client_update_service._append_website_findings(
        update,
        client_update_service.WebsiteEvidence(
            final_url="https://broken.example/",
            status_code=200,
            title="Broken Links",
            meta_description="A valid description.",
            h1_count=1,
            canonical="https://broken.example/",
            has_viewport=True,
            internal_link_count=8,
            checked_internal_link_count=8,
            broken_internal_link_count=2,
            robots_status=200,
            sitemap_status=200,
            audited_page_count=4,
        ),
    )

    assert any("2 of 8" in gap for gap in update.gaps)
    assert any("broken internal links" in action.casefold() for action in update.plan_30)
    assert update.structured_evidence["website"]["broken_internal_link_count"] == 2


def test_website_blocker_is_preserved_as_structured_evidence() -> None:
    update = client_update_service.ClientUpdate("client-1", "Blocked", "in_depth", "active")
    client_update_service._append_website_findings(
        update,
        client_update_service.WebsiteEvidence(
            url="https://blocked.example",
            blocker_code="website_dns_failed",
            blocker_detail="The domain did not resolve in public DNS.",
        ),
    )
    assert update.structured_evidence["website"]["blocker_code"] == "website_dns_failed"
    assert update.plan_30


def test_gbp_plan_does_not_claim_inspection_when_connection_is_missing() -> None:
    update = client_update_service.ClientUpdate("client-1", "No GBP", "in_depth", "active")
    # The helper only needs a database for its connection lookup; the empty
    # test database is provided by the shared fixture through SessionLocal.
    from app.database import SessionLocal

    with SessionLocal() as database:
        client_update_service._append_gbp(database, type("Client", (), {"id": "missing-client"})(), update)
    assert not any("inspection evidence" in action.casefold() for action in update.plan_60)


def test_unexpected_provider_failure_is_client_safe() -> None:
    update = client_update_service._blocked_client_update(
        type("Client", (), {"id": "client-1", "business_name": "Safe Client", "status": "active"})(),
        RuntimeError("Authorization: Bearer super-secret-token"),
    )
    assert "super-secret-token" not in update.blockers[0]
    assert "provider connection" in update.blockers[0]


def test_search_console_failure_explains_the_specific_fix(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routes import search_console, website_metrics

    monkeypatch.setattr(
        website_metrics,
        "sync_metrics",
        lambda _request, _database: {
            "snapshots": [],
            "unmatched_tracker_sites": [],
            "reused_existing": True,
        },
    )
    monkeypatch.setattr(
        client_update_service,
        "probe_website",
        lambda _url: client_update_service.WebsiteEvidence(
            final_url="https://authorized.example/",
            status_code=200,
            title="Authorized Auto Repair",
            meta_description="Local automotive service.",
            h1_count=1,
            canonical="https://authorized.example/",
            has_viewport=True,
            has_local_business_schema=True,
            has_phone_link=True,
            internal_link_count=5,
            robots_status=200,
            sitemap_status=200,
            audited_page_count=1,
        ),
    )
    monkeypatch.setattr(
        search_console,
        "sync_search_console",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPException(status_code=502, detail="search_console_authorization_failed")
        ),
    )
    with TestClient(app) as api:
        client_id = _client(api, "Auth Failure")
        with SessionLocal() as database:
            database.add(
                models.SearchConsoleConnection(
                    client_id=client_id,
                    property_url="sc-domain:authorized.example",
                    connection_status="connected",
                )
            )
            database.commit()
            client = database.get(models.Client, client_id)
            report = client_update_service.generate_portfolio_update(
                database, mode="in_depth", client=client
            )
            update = report.clients[0]

    assert any("authorization_failed" in blocker for blocker in update.blockers)
    assert any("Reconnect Google OAuth" in need for need in update.needs)


def test_search_console_query_opportunity_becomes_actionable_gap(monkeypatch) -> None:
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as api:
        client_id = _client(api, "Search Opportunity")
        with SessionLocal() as database:
            client = database.get(models.Client, client_id)
            connection = models.SearchConsoleConnection(
                client_id=client_id,
                property_url="sc-domain:search-opportunity.example.com",
                last_query_rows=[
                    {"key": "brake repair", "clicks": 0, "impressions": 42, "ctr": 0.0, "position": 8.0}
                ],
                last_page_rows=[],
            )
            database.add(connection)
            database.flush()
            monkeypatch.setattr(
                "app.routes.search_console.sync_search_console",
                lambda *_args, **_kwargs: [
                    SimpleNamespace(metric_name="search_clicks", value=8),
                    SimpleNamespace(metric_name="impressions", value=42),
                ],
            )
            update = client_update_service.ClientUpdate(client_id, client.business_name, "in_depth", client.status)
            client_update_service._refresh_search_console(database, client, update)

    assert any("zero clicks" in gap for gap in update.gaps)
    assert any("titles and descriptions" in action.casefold() for action in update.plan_30)
    assert update.structured_evidence["search_console"]["query_rows"][0]["key"] == "brake repair"


def test_in_depth_audit_finding_can_enter_normal_task_approval_flow(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routes import website_metrics

    monkeypatch.setattr(
        website_metrics,
        "sync_metrics",
        lambda _request, _database: {"snapshots": [], "unmatched_tracker_sites": [], "reused_existing": False},
    )
    monkeypatch.setattr(
        client_update_service,
        "probe_website",
        lambda _url: client_update_service.WebsiteEvidence(
            final_url="https://audit.example/",
            status_code=200,
            title=None,
            h1_count=1,
            has_viewport=True,
            internal_link_count=4,
            robots_status=200,
            sitemap_status=200,
            audited_page_count=1,
        ),
    )
    with TestClient(app) as api:
        client_id = _client(api, "Audit Task Handoff")
        report = api.post(
            f"/clients/{client_id}/reports",
            json={
                "report_type": "internal",
                "period_start": date.today().replace(day=1).isoformat(),
                "period_end": date.today().isoformat(),
                "generated_by": "Agency Owner",
                "update_mode": "in_depth",
            },
        )
        finding = next(item for item in report.json()["snapshot_data"]["findings"] if item["source"] == "in_depth_audit")
        task = api.post(
            f"/clients/{client_id}/tasks",
            json={
                "source_finding_id": finding["id"],
                "title": finding["title"],
                "requested_outcome": finding["recommended_action"],
                "reason": finding["explanation"],
                "estimated_effort": "30 minutes",
                "risk": "medium",
                "required_access": [],
            },
        )

    assert report.status_code == 201, report.text
    assert task.status_code == 201, task.text
    assert task.json()["source_finding_id"] == finding["id"]


def test_one_provider_exception_becomes_a_blocker_without_aborting_portfolio(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as api:
        first_id = _client(api, "Partial Provider One")
        second_id = _client(api, "Partial Provider Two")
        with SessionLocal() as database:
            first = database.get(models.Client, first_id)
            second = database.get(models.Client, second_id)

            def fake_audit(_database, client):
                if client.id == first_id:
                    raise client_update_service.SearchConsoleIntegrationError(
                        "search_console_temporarily_unavailable", retryable=True
                    )
                return client_update_service.ClientUpdate(
                    client.id, client.business_name, "in_depth", client.status,
                    facts=["Second client audit completed."],
                )

            monkeypatch.setattr(client_update_service, "_in_depth_client_update", fake_audit)
            report = client_update_service.generate_portfolio_update(database, mode="in_depth")

    blocked = next(item for item in report.clients if item.client_id == first_id)
    completed = next(item for item in report.clients if item.client_id == second_id)
    assert any("provider boundary" in item for item in blocked.blockers)
    assert any("rerun" in item.casefold() for item in blocked.needs)
    assert completed.facts == ["Second client audit completed."]


def test_slack_report_language_selects_simple_or_in_depth_scope() -> None:
    from app.slack_action_service import detect_owner_action

    portfolio = detect_owner_action("give me an in-depth report on all clients", has_mapped_client=False)
    simple = detect_owner_action("simple update on every client", has_mapped_client=False)
    scoped = detect_owner_action("run a detailed audit for this client", has_mapped_client=True)

    assert (portfolio.action_type, portfolio.mode) == ("generate_client_update", "in_depth")
    assert (simple.action_type, simple.mode) == ("generate_client_update", "simple")
    assert (scoped.action_type, scoped.mode) == ("generate_client_update", "in_depth")


def test_slack_can_approve_the_single_presented_task_without_repeating_id() -> None:
    from app.slack_action_service import detect_owner_action

    for wording in ("approve this", "approve it", "yes approve", "go ahead with it", "proceed"):
        action = detect_owner_action(wording, has_mapped_client=True)
        assert action is not None
        assert action.action_type == "decide_task"
        assert action.target_status == "approved"

    assert detect_owner_action("approve this", has_mapped_client=False) is None


def test_slack_daily_workflow_can_opt_into_proposed_tasks() -> None:
    from app.slack_action_service import detect_owner_action

    action = detect_owner_action("enable in-depth daily plans with tasks", has_mapped_client=True)

    assert action is not None
    assert action.action_type == "set_workflow"
    assert action.workflow == "daily_client_plan"
    assert action.workflow_depth == "in_depth"
    assert action.workflow_create_tasks is True


def test_simple_portfolio_report_runs_as_a_real_slack_action(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from app import slack_conversation_service, slack_service
    from tests.test_slack import (
        FakeSlackAdapter,
        connect_fake_slack,
        post_signed_slack_event,
    )

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        slack_conversation_service,
        "answer_question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recognized report commands must not use the generic AI answer path")
        ),
    )
    channel = slack_service.SlackChannel("C_PORTFOLIO_REPORT", "portfolio-report")
    adapter.channel_states[channel.id] = channel
    with TestClient(app) as api:
        _client(api, "Slack Portfolio")
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_portfolio_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_OWNER",
                    "channel": channel.id,
                    "text": "<@U_BOT> give me a simple report on all clients",
                },
            },
        )

    assert response.status_code == 200
    assert "Simple saved-data update" in adapter.messages[-1]["text"]
    assert "Saved Max records" in adapter.messages[-1]["text"]
