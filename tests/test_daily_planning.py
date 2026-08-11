"""Daily plans turn evidence and task state into deduplicated work queues."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import select

from app import client_update_service, daily_planning_service, job_service, models
from app.database import SessionLocal, create_database


def _saved_client(database, label: str) -> models.Client:
    client = models.Client(
        business_name=f"{label} {uuid4().hex[:8]}",
        service_start_date=date.today(),
    )
    database.add(client)
    database.flush()
    return client


def _task(database, client: models.Client, title: str, status: str) -> models.Task:
    finding = models.Finding(
        client_id=client.id,
        rule_key=f"daily-plan:{uuid4().hex}",
        title=title,
        explanation=f"Evidence for {title}",
        evidence={"source": "test evidence"},
        source="daily_plan_test",
        severity="warning",
        confidence="confirmed",
        recommended_action=f"Complete {title}",
        status="open",
    )
    database.add(finding)
    database.flush()
    task = models.Task(
        client_id=client.id,
        source_finding_id=finding.id,
        title=title,
        requested_outcome=f"Complete {title}",
        reason=finding.explanation,
        estimated_effort="30 minutes",
        risk="low",
        required_access=[],
        status=status,
    )
    database.add(task)
    database.flush()
    return task


def test_simple_daily_plan_prioritizes_ready_approval_and_blocked_work() -> None:
    create_database()
    with SessionLocal() as database:
        client = _saved_client(database, "Daily Priority")
        ready = _task(database, client, "Fix the booking link", "ready")
        proposed = _task(database, client, "Improve the service page", "proposed")
        blocked = _task(database, client, "Connect Search Console", "blocked")
        database.commit()
        plans = daily_planning_service.generate_daily_plans(
            database,
            depth="simple",
            focus="all",
            created_by="test planner",
            client=client,
        )
        plan = plans[0]
        rendered = daily_planning_service.render_slack_daily_plans(database, plans)

    by_source = {item["source"]: item for item in plan.items}
    assert by_source[f"task:{ready.id}"]["bucket"] == "ready_now"
    assert by_source[f"task:{ready.id}"]["task_id"] == ready.id
    assert by_source[f"task:{ready.id}"]["expected_result"]
    assert by_source[f"task:{ready.id}"]["success_metric"]
    assert by_source[f"task:{ready.id}"]["verification_window"]
    assert by_source[f"task:{proposed.id}"]["bucket"] == "needs_approval"
    assert by_source[f"task:{blocked.id}"]["bucket"] == "blocked"
    assert "Can do now" in rendered
    assert "Needs approval" in rendered
    assert "Blocked / access needed" in rendered
    assert "Expected result:" in rendered
    assert "Success metric:" in rendered


def test_verified_task_stays_in_daily_plan_until_outcome_is_measured() -> None:
    create_database()
    with SessionLocal() as database:
        client = _saved_client(database, "Outcome Followup")
        task = _task(database, client, "Publish the service page", "verified")
        database.commit()

        pending_plan = daily_planning_service.generate_daily_plans(
            database,
            depth="simple",
            focus="all",
            created_by="test planner",
            client=client,
            plan_date=date.today(),
        )[0]
        pending_item = next(item for item in pending_plan.items if item["task_id"] == task.id)
        assert pending_item["bucket"] == "needs_outcome_measurement"
        assert f"record outcome for task {task.id}" in pending_item["next_step"]

        database.add(
            models.OutcomeMeasurement(
                operation_key=f"daily-plan-outcome:{task.id}",
                client_id=client.id,
                task_id=task.id,
                metric_name="Organic clicks",
                baseline_value=100,
                observed_value=125,
                unit="clicks",
                assessment="met",
                source_type="live_api",
                source_reference="Search Console export",
                evidence=["Export shows 125 clicks"],
                notes="Measured after the verification window.",
                recorded_by="Agency Owner",
                observed_at=datetime.utcnow(),
            )
        )
        database.commit()
        measured_plan = daily_planning_service.generate_daily_plans(
            database,
            depth="simple",
            focus="all",
            created_by="refreshed planner",
            client=client,
            plan_date=date.today(),
        )[0]

    assert not any(item.get("task_id") == task.id for item in measured_plan.items)


def test_in_depth_seo_plan_persists_30_60_90_day_recommendations(monkeypatch) -> None:
    create_database()
    with SessionLocal() as database:
        client = _saved_client(database, "SEO Roadmap")
        database.commit()
        update = client_update_service.ClientUpdate(
            client_id=client.id,
            business_name=client.business_name,
            mode="in_depth",
            status=client.status,
            facts=["Website reachable."],
            gaps=["Sitemap is missing."],
            blockers=["Search Console is not connected."],
            needs=["Connect the exact Search Console property."],
            plan_30=["Publish an XML sitemap and submit it in Search Console."],
            plan_60=["Improve service pages and internal links."],
            plan_90=["Compare organic clicks and qualified leads against this audit."],
            sources=["Fresh website crawl"],
            persisted_finding_ids=["finding_sitemap"],
            structured_evidence={"website": {"sitemap_status": 404}},
        )
        monkeypatch.setattr(
            daily_planning_service,
            "generate_portfolio_update",
            lambda _database, *, mode, client=None: client_update_service.PortfolioUpdate(
                mode=mode, clients=[update]
            ),
        )
        first = daily_planning_service.generate_daily_plans(
            database,
            depth="in_depth",
            focus="seo",
            created_by="test planner",
            client=client,
        )[0]
        second = daily_planning_service.generate_daily_plans(
            database,
            depth="in_depth",
            focus="seo",
            created_by="refreshed planner",
            client=client,
        )[0]
        database.commit()
        count = len(
            list(
                database.scalars(
                    select(models.DailyClientPlan).where(
                        models.DailyClientPlan.client_id == client.id,
                        models.DailyClientPlan.plan_date == date.today(),
                    )
                )
            )
        )

    assert first.id == second.id
    assert count == 1
    assert second.source_summary["finding_ids"] == ["finding_sitemap"]
    assert second.source_summary["structured_evidence"]["website"]["sitemap_status"] == 404
    assert {item["horizon"] for item in second.items} >= {
        "today",
        "0-30_days",
        "31-60_days",
        "61-90_days",
    }
    assert any(item["bucket"] == "blocked" for item in second.items)
    assert all(item.get("expected_result") for item in second.items)
    assert all(item.get("success_metric") for item in second.items)
    assert all(item.get("verification_window") for item in second.items)


def test_daily_plan_can_create_proposed_tasks_without_approving_them(monkeypatch) -> None:
    create_database()
    with SessionLocal() as database:
        client = _saved_client(database, "Auto Proposal Plan")
        database.commit()
        update = client_update_service.ClientUpdate(
            client_id=client.id,
            business_name=client.business_name,
            mode="in_depth",
            status=client.status,
            plan_30=["Publish the approved service page and verify indexing."],
            sources=["Fresh website crawl"],
        )
        monkeypatch.setattr(
            daily_planning_service,
            "generate_portfolio_update",
            lambda _database, *, mode, client=None: client_update_service.PortfolioUpdate(
                mode=mode, clients=[update]
            ),
        )
        plan = daily_planning_service.generate_daily_plans(
            database,
            depth="in_depth",
            focus="seo",
            created_by="scheduled planner",
            client=client,
            create_tasks=True,
        )[0]
        plan_items = list(plan.items)
        database.commit()
        proposed = list(
            database.scalars(
                select(models.Task).where(models.Task.client_id == client.id)
            )
        )

    assert len(proposed) == 1
    assert proposed[0].status == "proposed"
    assert plan_items[0]["task_id"] == proposed[0].id


def test_daily_plan_job_generates_plan_and_actionable_notification() -> None:
    create_database()
    now = datetime.utcnow()
    with SessionLocal() as database:
        client = _saved_client(database, "Scheduled Daily")
        _task(database, client, "Review the approved landing page", "approved")
        job = models.ScheduledJob(
            job_key=f"daily-plan-test:{uuid4().hex}",
            job_type="daily_client_plan",
            client_id=client.id,
            interval_minutes=1440,
            next_run_at=now,
        )
        database.add(job)
        database.commit()
        job_id = job.id
        results = job_service.run_due_jobs(database, now=now)
        plan = database.scalar(
            select(models.DailyClientPlan).where(models.DailyClientPlan.client_id == client.id)
        )
        notification = database.scalar(
            select(models.Notification).where(
                models.Notification.related_record_type == "daily_client_plan",
                models.Notification.related_record_id == plan.id,
            )
        )

    own_result = next(item for item in results if item["job_id"] == job_id)
    assert own_result["status"] == "completed"
    assert plan.items[0]["bucket"] == "ready_now"
    assert "complete plan" in notification.requested_action


def test_slack_detects_daily_seo_fulfillment_and_scrape_requests() -> None:
    from app.slack_action_service import detect_owner_action

    daily = detect_owner_action("today's tasks for this client", has_mapped_client=True)
    seo = detect_owner_action("make an SEO roadmap for this client", has_mapped_client=True)
    fulfillment = detect_owner_action("fulfillment plan for this client", has_mapped_client=True)
    scrape = detect_owner_action("crawl and inspect this website", has_mapped_client=True)
    convert = detect_owner_action("create a task from daily plan item 2", has_mapped_client=True)
    convert_word = detect_owner_action("make a task from daily plan item one", has_mapped_client=True)

    assert (daily.action_type, daily.mode, daily.workflow) == ("generate_daily_plan", "simple", "all")
    assert (seo.action_type, seo.mode, seo.workflow) == ("generate_daily_plan", "in_depth", "seo")
    assert (fulfillment.action_type, fulfillment.workflow) == ("generate_daily_plan", "fulfillment")
    assert (scrape.action_type, scrape.mode) == ("generate_client_update", "in_depth")
    assert (convert.action_type, convert.daily_plan_item_index) == ("convert_daily_plan_item", 1)
    assert (convert_word.action_type, convert_word.daily_plan_item_index) == ("convert_daily_plan_item", 0)


def test_in_depth_plan_recommendation_converts_once_into_approval_task(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with SessionLocal() as database:
        client = _saved_client(database, "Plan To Task")
        database.commit()
        update = client_update_service.ClientUpdate(
            client_id=client.id,
            business_name=client.business_name,
            mode="in_depth",
            status=client.status,
            gaps=["Homepage title is missing."],
            plan_30=["Write a unique homepage title targeting the primary service and location."],
            sources=["Fresh public website crawl"],
        )
        monkeypatch.setattr(
            daily_planning_service,
            "generate_portfolio_update",
            lambda _database, *, mode, client=None: client_update_service.PortfolioUpdate(mode=mode, clients=[update]),
        )
        with TestClient(app) as api:
            generated = api.post(
                f"/clients/{client.id}/daily-plan",
                json={"depth": "in_depth", "focus": "seo", "created_by": "test"},
            )
            plan = generated.json()
            item_index = next(index for index, item in enumerate(plan["items"]) if item["source"] == "fresh_audit_recommendation")
            created = api.post(
                f"/clients/{client.id}/daily-plan/items/{item_index}/task",
                json={"created_by": "test"},
            )
            repeated = api.post(
                f"/clients/{client.id}/daily-plan/items/{item_index}/task",
                json={"created_by": "test"},
            )

    assert generated.status_code == 200
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "proposed"
    assert repeated.status_code == 201
    assert repeated.json()["id"] == created.json()["id"]


def test_recommendation_runs_through_approval_codex_handoff_and_verification(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    create_database()
    with SessionLocal() as database:
        client = _saved_client(database, "Complete Fulfillment Loop")
        database.commit()
        update = client_update_service.ClientUpdate(
            client_id=client.id,
            business_name=client.business_name,
            mode="in_depth",
            status=client.status,
            gaps=["Homepage title is missing."],
            plan_30=["Update the homepage title to target the primary service and location."],
            sources=["Fresh public website crawl"],
        )
        monkeypatch.setattr(
            daily_planning_service,
            "generate_portfolio_update",
            lambda _database, *, mode, client=None: client_update_service.PortfolioUpdate(mode=mode, clients=[update]),
        )
        with TestClient(app) as api:
            generated = api.post(
                f"/clients/{client.id}/daily-plan",
                json={"depth": "in_depth", "focus": "seo", "created_by": "test"},
            ).json()
            item_index = next(index for index, item in enumerate(generated["items"]) if item["source"] == "fresh_audit_recommendation")
            task = api.post(
                f"/clients/{client.id}/daily-plan/items/{item_index}/task",
                json={"created_by": "test"},
            ).json()
            api.post(
                f"/clients/{client.id}/website-connection",
                json={"external_project_id": "prj-complete-loop", "project_name": "complete-loop", "production_url": "https://complete-loop.example.com"},
            )
            api.post(
                f"/clients/{client.id}/github-repository",
                json={"owner": "agency", "repository_name": "complete-loop", "repository_url": "https://github.com/agency/complete-loop", "default_branch": "main"},
            )
            approved = api.post(
                f"/tasks/{task['id']}/decision",
                json={"decision": "approved", "decision_maker": "Agency Owner"},
            )
            packets = api.get(f"/clients/{client.id}/codex-work-packets").json()
            packet = packets[0]
            handed_off = api.post(
                f"/codex-work-packets/{packet['id']}/handoff",
                json={"handed_off_by": "Agency Owner"},
            )
            result = api.post(
                f"/codex-work-packets/{packet['id']}/result",
                json={
                    "operation_key": "complete-loop-codex-result",
                    "outcome": "completed",
                    "submitted_by": "Codex",
                    "summary": "Updated the homepage title and returned the build evidence.",
                    "changed_files": ["app/page.py"],
                    "tests": [{"name": "build", "status": "passed"}],
                    "commit_shas": ["complete123"],
                        "deployment_url": "https://complete-loop.example.com",
                        "evidence": ["Production page returned HTTP 200"],
                        "verification_data": {"acceptance_checks": [
                            {"criterion": "requested outcome", "status": "passed", "evidence": "Title change reviewed"},
                            {"criterion": "allowed files", "status": "passed", "evidence": "Packet scope reviewed"},
                            {"criterion": "client target", "status": "passed", "evidence": "Production domain reviewed"},
                        ]},
                    },
            )
            verified = api.post(
                f"/executions/{result.json()['execution']['id']}/verifications",
                json={
                    "decision_key": "complete-loop-verification",
                    "outcome": "verified",
                    "reviewer": "Agency Owner",
                    "explanation": "The returned change matches the approved task and the production evidence.",
                    "review_evidence": ["Production page checked", "Build passed"],
                    "correct_client_confirmed": True,
                    "approved_task_followed": True,
                    "output_exists": True,
                    "result_matches_requested_outcome": True,
                    "no_unexpected_changes": True,
                },
            )
            final_task = api.get(f"/tasks/{task['id']}")

    assert approved.status_code == 200
    assert len(packets) == 1
    assert handed_off.status_code == 200
    assert result.status_code == 200
    assert verified.status_code == 201, verified.text
    assert final_task.json()["status"] == "verified"


def test_signed_slack_returns_and_persists_todays_client_tasks(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import app
    from app import slack_conversation_service
    from tests.test_slack import (
        FakeSlackAdapter,
        connect_fake_slack,
        create_client,
        post_signed_slack_event,
    )

    adapter = FakeSlackAdapter()
    connect_fake_slack(monkeypatch, adapter)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "event-secret")
    monkeypatch.setattr(
        slack_conversation_service,
        "answer_question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily plan must execute as an action")
        ),
    )
    with TestClient(app) as api:
        client_id = create_client(api, f"Slack Daily {uuid4().hex[:8]}")
        connection = api.post(f"/clients/{client_id}/slack-channel").json()["connection"]
        with SessionLocal() as database:
            client = database.get(models.Client, client_id)
            task = _task(database, client, "Publish the approved brake service update", "ready")
            database.commit()
            task_id = task.id
        response = post_signed_slack_event(
            api,
            {
                "type": "event_callback",
                "team_id": adapter.workspace.id,
                "event_id": f"Ev_daily_{uuid4().hex}",
                "event": {
                    "type": "app_mention",
                    "user": "U_CHANNEL_MEMBER",
                    "channel": connection["channel_id"],
                    "text": "<@U_BOT> give me today's tasks for this client",
                },
            },
        )
        with SessionLocal() as database:
            plan = database.scalar(
                select(models.DailyClientPlan).where(
                    models.DailyClientPlan.client_id == client_id,
                    models.DailyClientPlan.plan_date == date.today(),
                )
            )

    assert response.status_code == 200
    assert plan is not None
    assert any(item["source"] == f"task:{task_id}" for item in plan.items)
    assert "Can do now" in adapter.messages[-1]["text"]
    with SessionLocal() as database:
        daily_job = database.scalar(
            select(models.ScheduledJob).where(
                models.ScheduledJob.job_key == f"daily-plan:{client_id}"
            )
        )
    assert daily_job is not None
    assert daily_job.enabled is True


def test_daily_plan_api_generates_reads_and_lists_plan() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as api:
        created = api.post(
            "/clients",
            json={"business_name": f"Plan API {uuid4().hex[:8]}", "service_start_date": str(date.today())},
        )
        client_id = created.json()["id"]
        generated = api.post(
            f"/clients/{client_id}/daily-plan",
            json={"depth": "simple", "focus": "reporting", "created_by": "API test"},
        )
        read = api.get(f"/clients/{client_id}/daily-plan")
        listed = api.get("/daily-plans")

    assert generated.status_code == 200
    assert generated.json()["focus"] == "reporting"
    assert read.json()["id"] == generated.json()["id"]
    assert any(item["id"] == generated.json()["id"] for item in listed.json())


def test_client_workspace_can_generate_and_render_daily_plan() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as api:
        created = api.post(
            "/clients",
            json={"business_name": f"Plan UI {uuid4().hex[:8]}", "service_start_date": str(date.today())},
        )
        client_id = created.json()["id"]
        generated = api.post(
            f"/dashboard/clients/{client_id}/daily-plan",
            data={"depth": "simple", "focus": "all"},
            follow_redirects=False,
        )
        converted = api.post(
            f"/dashboard/clients/{client_id}/daily-plan/items/0/task",
            follow_redirects=False,
        )
        page = api.get(f"/dashboard/clients/{client_id}?section=plan")

    assert generated.status_code == 303
    assert converted.status_code == 303
    assert page.status_code == 200
    assert "Today's client plan" in page.text
    assert "Evidence used" in page.text
    assert "Daily plan" in page.text
    assert "Create approval task" not in page.text
