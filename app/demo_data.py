"""Seed the read-only demo deployment with invented agency data.

Every business, domain, phone number, and metric below is fabricated for the
public demo. Nothing here is copied from a real client, and the seeder only ever
runs against a database that demo mode has already claimed.

The set is deliberately uneven: clients sit at different points in the lifecycle
so the dashboard shows an onboarding client, a client waiting on profile review,
healthy clients, and a client with an unavailable provider. That makes the
screens demonstrate the actual product states rather than one happy path.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


TODAY = date(2026, 8, 25)
NOW = datetime(2026, 8, 25, 14, 30)


def _client_spec() -> list[dict]:
    """Describe each demo client and how far through the lifecycle it is."""
    return [
        {
            "id": "demo-cl-0001",
            "business_name": "Ridgeline Garage Doors",
            "service_start_date": date(2026, 2, 3),
            "status": "active",
            "domain": "ridgeline-garage.example",
            "phone": "(555) 0142-8890",
            "email": "owner@ridgeline-garage.example",
            "areas": ["Boulder", "Longmont", "Louisville", "Lafayette"],
            "hours": "Mon-Fri 7:00-18:00, Sat 8:00-14:00",
            "colors": ["#1f4e79", "#f2a900"],
            "project": "ridgeline-garage-doors",
            "profile": "official",
            "website": True,
            "search_console": "connected",
        },
        {
            "id": "demo-cl-0002",
            "business_name": "Harborview Epoxy Floors",
            "service_start_date": date(2026, 3, 18),
            "status": "active",
            "domain": "harborview-epoxy.example",
            "phone": "(555) 0166-2231",
            "email": "hello@harborview-epoxy.example",
            "areas": ["Tacoma", "Puyallup", "Gig Harbor"],
            "hours": "Mon-Sat 8:00-17:00",
            "colors": ["#0f3d3e", "#c9a227"],
            "project": "harborview-epoxy-floors",
            "profile": "official",
            "website": True,
            "search_console": "connected",
        },
        {
            "id": "demo-cl-0003",
            "business_name": "Cedar & Stone Landscaping",
            "service_start_date": date(2026, 5, 6),
            "status": "active",
            "domain": "cedarandstone.example",
            "phone": "(555) 0119-4477",
            "email": "team@cedarandstone.example",
            "areas": ["Asheville", "Hendersonville", "Black Mountain"],
            "hours": "Mon-Fri 7:30-16:30",
            "colors": ["#2f5d3a", "#e8e0d0"],
            "project": "cedar-and-stone-landscaping",
            "profile": "review",
            "website": True,
            "search_console": "unavailable",
        },
        {
            "id": "demo-cl-0004",
            "business_name": "Northgate Auto Detailing",
            "service_start_date": date(2026, 6, 22),
            "status": "active",
            "domain": "northgate-detailing.example",
            "phone": "(555) 0188-3312",
            "email": "front-desk@northgate-detailing.example",
            "areas": ["Columbus", "Dublin", "Westerville"],
            "hours": "Tue-Sat 9:00-18:00",
            "colors": ["#111827", "#dc2626"],
            "project": "northgate-auto-detailing",
            "profile": "official",
            "website": True,
            "search_console": "connected",
        },
        {
            "id": "demo-cl-0005",
            "business_name": "Bellweather Roofing Co.",
            "service_start_date": date(2026, 7, 29),
            "status": "active",
            "domain": "bellweather-roofing.example",
            "phone": "(555) 0173-9028",
            "email": "office@bellweather-roofing.example",
            "areas": ["Springfield", "Chatham", "Rochester"],
            "hours": "Mon-Fri 8:00-17:00",
            "colors": ["#3b3b58", "#f4f4f8"],
            "project": "bellweather-roofing",
            "profile": "official",
            "website": True,
            "search_console": "pending",
        },
        {
            "id": "demo-cl-0006",
            "business_name": "Palmetto Pressure Washing",
            "service_start_date": date(2026, 8, 19),
            "status": "onboarding",
            "domain": "palmetto-pressure.example",
            "phone": "(555) 0155-7741",
            "email": "book@palmetto-pressure.example",
            "areas": ["Charleston", "Mount Pleasant", "Summerville"],
            "hours": "Mon-Sat 8:00-18:00",
            "colors": ["#14532d", "#bef264"],
            "project": None,
            "profile": "none",
            "website": False,
            "search_console": "not_connected",
        },
    ]


def _findings_for(client_id: str, name: str) -> list[dict]:
    """Give each client a small, plausible set of evidence-backed issues."""
    catalogue = {
        "demo-cl-0001": [
            {
                "rule_key": "gbp.hours_mismatch",
                "title": "Google Business Profile hours disagree with the website",
                "explanation": (
                    "The profile lists Saturday hours ending at 12:00 while the website "
                    "footer lists 14:00. Callers arriving after noon on Saturday are "
                    "being turned away."
                ),
                "severity": "high",
                "confidence": "high",
                "source": "google_business_profile",
                "recommended_action": "Publish the website's Saturday hours to the profile and re-verify.",
                "status": "open",
            },
            {
                "rule_key": "seo.missing_service_page",
                "title": "No dedicated page for spring replacement",
                "explanation": (
                    "Spring replacement is the highest-volume query in the service area "
                    "but resolves to the generic repair page, which does not mention it."
                ),
                "severity": "medium",
                "confidence": "high",
                "source": "search_console",
                "recommended_action": "Publish a spring-replacement service page and link it from the repair page.",
                "status": "open",
            },
        ],
        "demo-cl-0002": [
            {
                "rule_key": "site.slow_largest_contentful_paint",
                "title": "Gallery page is slow on mobile",
                "explanation": (
                    "The gallery ships eleven full-resolution images. Largest contentful "
                    "paint measured 4.8s on a throttled mobile connection."
                ),
                "severity": "medium",
                "confidence": "high",
                "source": "website_audit",
                "recommended_action": "Serve resized WebP images and defer below-the-fold gallery loading.",
                "status": "in_progress",
            },
        ],
        "demo-cl-0003": [
            {
                "rule_key": "access.search_console_unavailable",
                "title": "Search Console access cannot be verified",
                "explanation": (
                    "The stored Search Console grant returned a permission error on the "
                    "last three checks. Query data for this client is unavailable, not zero."
                ),
                "severity": "high",
                "confidence": "high",
                "source": "search_console",
                "recommended_action": "Ask the owner to re-grant delegated access, then re-run verification.",
                "status": "open",
            },
        ],
        "demo-cl-0004": [
            {
                "rule_key": "gbp.review_response_gap",
                "title": "Nine reviews are unanswered",
                "explanation": (
                    "Nine reviews from the last 60 days have no owner response, including "
                    "two at three stars or below."
                ),
                "severity": "medium",
                "confidence": "high",
                "source": "google_business_profile",
                "recommended_action": "Draft responses for the two low-star reviews first, then the remainder.",
                "status": "open",
            },
        ],
        "demo-cl-0005": [
            {
                "rule_key": "site.missing_tracking",
                "title": "Contact form submissions are not tracked",
                "explanation": (
                    "The contact form posts successfully but fires no conversion event, so "
                    "form volume cannot be attributed to any channel."
                ),
                "severity": "high",
                "confidence": "medium",
                "source": "website_audit",
                "recommended_action": "Add a submission event and confirm it in a live test before reporting on it.",
                "status": "open",
            },
        ],
        "demo-cl-0006": [],
    }
    return catalogue.get(client_id, [])


def _tasks_for(client_id: str) -> list[dict]:
    """Return the demo work queue, spread across the approval lifecycle."""
    catalogue = {
        "demo-cl-0001": [
            {
                "title": "Correct Saturday hours on the Google Business Profile",
                "requested_outcome": "Profile Saturday hours read 8:00-14:00 and match the website footer.",
                "reason": "Callers are being turned away after noon on Saturdays.",
                "expected_result": "Profile hours and website footer agree on re-check.",
                "success_metric": "Saturday hours match on both sources.",
                "estimated_effort": "15 minutes",
                "risk": "low",
                "required_access": ["google_business_profile"],
                "status": "approved",
            },
            {
                "title": "Publish a spring replacement service page",
                "requested_outcome": "A spring-replacement page exists, is internally linked, and is indexable.",
                "reason": "Highest-volume query in the area has no matching page.",
                "expected_result": "Page is live and appears in the sitemap.",
                "success_metric": "Impressions for spring replacement queries.",
                "estimated_effort": "3 hours",
                "risk": "low",
                "required_access": ["website"],
                "status": "proposed",
            },
        ],
        "demo-cl-0002": [
            {
                "title": "Compress and lazy-load the gallery images",
                "requested_outcome": "Gallery largest contentful paint is under 2.5s on throttled mobile.",
                "reason": "Gallery ships eleven full-resolution images.",
                "expected_result": "Re-measured LCP is under 2.5s.",
                "success_metric": "Mobile largest contentful paint.",
                "estimated_effort": "2 hours",
                "risk": "low",
                "required_access": ["website", "github"],
                "status": "in_progress",
            },
        ],
        "demo-cl-0003": [
            {
                "title": "Re-establish Search Console access",
                "requested_outcome": "A verified Search Console grant returns query data for the property.",
                "reason": "Three consecutive permission errors on the stored grant.",
                "expected_result": "Verification check passes and query rows return.",
                "success_metric": "Provider verification status.",
                "estimated_effort": "30 minutes",
                "risk": "low",
                "required_access": ["search_console"],
                "status": "blocked",
            },
        ],
        "demo-cl-0004": [
            {
                "title": "Respond to the two lowest-rated reviews",
                "requested_outcome": "Both sub-three-star reviews have a published owner response.",
                "reason": "Unanswered low-star reviews are the most visible on the profile.",
                "expected_result": "Responses visible on the public profile.",
                "success_metric": "Count of unanswered reviews.",
                "estimated_effort": "45 minutes",
                "risk": "medium",
                "required_access": ["google_business_profile"],
                "status": "proposed",
            },
        ],
        "demo-cl-0005": [
            {
                "title": "Instrument the contact form conversion event",
                "requested_outcome": "A submission fires a tracked conversion event confirmed by a live test.",
                "reason": "Form volume currently cannot be attributed to any channel.",
                "expected_result": "Test submission appears in the analytics event stream.",
                "success_metric": "Tracked form submissions per week.",
                "estimated_effort": "1 hour",
                "risk": "low",
                "required_access": ["website"],
                "status": "approved",
            },
        ],
        "demo-cl-0006": [],
    }
    return catalogue.get(client_id, [])


def demo_data_present(database: Session) -> bool:
    """Report whether this database already holds the demo portfolio."""
    return database.scalar(select(models.Client.id).limit(1)) is not None


def seed_demo_data(database: Session) -> int:
    """Populate an empty database with the demo portfolio.

    The seeder is idempotent by refusing to run when any client already exists,
    so a warm serverless instance never duplicates rows.
    """
    if demo_data_present(database):
        return 0

    created = 0
    for index, spec in enumerate(_client_spec()):
        client = models.Client(
            id=spec["id"],
            business_name=spec["business_name"],
            service_start_date=spec["service_start_date"],
            status=spec["status"],
            created_at=NOW - timedelta(days=120 - index * 12),
            updated_at=NOW - timedelta(days=index),
        )
        database.add(client)
        # These rows carry explicit string foreign keys rather than ORM
        # relationships, so the unit of work cannot infer their order. Each
        # stage is flushed before the rows that point at it are added.
        database.flush()
        created += 1

        subscription = models.ClientSubscription(
            id=f"demo-sub-{index:04d}",
            client_id=spec["id"],
            status="active" if spec["status"] == "active" else "trial",
            plan="agency",
            provider="manual",
            current_period_start=NOW - timedelta(days=25),
            current_period_end=NOW + timedelta(days=5),
            metadata_json={"seat_count": 1, "demo": True},
        )
        database.add(subscription)

        if spec["profile"] == "none":
            # An onboarding client that has not submitted an intake yet is what
            # the dashboard's "action required" state is built to surface.
            continue

        intake = models.Intake(
            id=f"demo-in-{index:04d}",
            client_id=spec["id"],
            phone_number=spec["phone"],
            email=spec["email"],
            brand_colors=spec["colors"],
            domain=spec["domain"],
            business_hours=spec["hours"],
            service_areas=spec["areas"],
            google_business_profile=f"https://maps.example/place/{spec['project']}",
            enabled_workflows=["local_seo", "website", "reporting"],
            status="processed",
            submitted_at=NOW - timedelta(days=90 - index * 10),
        )
        database.add(intake)
        database.flush()

        proposal = models.InterpretationProposal(
            id=f"demo-ip-{index:04d}",
            intake_id=intake.id,
            client_id=spec["id"],
            profile_data={
                "business_name": spec["business_name"],
                "primary_services": ["Repair", "Installation", "Maintenance"],
                "service_areas": spec["areas"],
                "hours": spec["hours"],
            },
            missing_information=[] if spec["profile"] == "official" else ["Service-area boundary for outlying towns"],
            conflicting_information=[],
            processing_status="completed",
            processed_at=NOW - timedelta(days=88 - index * 10),
        )
        database.add(proposal)
        database.flush()

        version = models.ProfileVersion(
            id=f"demo-pv-{index:04d}",
            source_proposal_id=proposal.id,
            intake_id=intake.id,
            client_id=spec["id"],
            version_number=1,
            profile_data=proposal.profile_data,
            status="approved" if spec["profile"] == "official" else "pending",
            decision_maker="owner@demo-agency.example" if spec["profile"] == "official" else None,
            decision_reason="Matches the intake and the verified profile." if spec["profile"] == "official" else None,
            decided_at=NOW - timedelta(days=85 - index * 10) if spec["profile"] == "official" else None,
        )
        database.add(version)
        database.flush()

        if spec["profile"] == "official":
            database.add(
                models.OfficialProfile(
                    id=f"demo-op-{index:04d}",
                    client_id=spec["id"],
                    approved_version_id=version.id,
                    profile_data=proposal.profile_data,
                    approved_by="owner@demo-agency.example",
                    approved_at=NOW - timedelta(days=85 - index * 10),
                )
            )

        if spec["website"]:
            database.add(
                models.WebsiteConnection(
                    id=f"demo-wc-{index:04d}",
                    client_id=spec["id"],
                    provider="vercel",
                    external_project_id=f"prj_demo_{index:04d}",
                    project_name=spec["project"],
                    production_url=f"https://{spec['domain']}",
                    connection_status="linked",
                    source="confirmed_vercel_import",
                    linked_at=NOW - timedelta(days=80 - index * 10),
                )
            )

        _seed_integrations(database, index, spec)
        _seed_health_and_findings(database, index, spec)
        _seed_metrics(database, index, spec)
        _seed_reports(database, index, spec)

    database.commit()
    return created


def _seed_integrations(database: Session, index: int, spec: dict) -> None:
    """Record provider connection state, including a deliberately broken one."""
    status_text = {
        "connected": "connected",
        "pending": "pending_verification",
        "unavailable": "unavailable",
        "not_connected": "not_connected",
    }[spec["search_console"]]
    issues = (
        ["Delegated access returned a permission error on the last three checks."]
        if spec["search_console"] == "unavailable"
        else []
    )
    database.add(
        models.IntegrationConnection(
            id=f"demo-ic-sc-{index:04d}",
            client_id=spec["id"],
            integration_name="Google Search Console",
            connection_status=status_text,
            data_source_type="live_api",
            last_checked_at=NOW - timedelta(hours=6),
            issues=issues,
        )
    )
    database.add(
        models.IntegrationConnection(
            id=f"demo-ic-gbp-{index:04d}",
            client_id=spec["id"],
            integration_name="Google Business Profile",
            connection_status="connected",
            data_source_type="live_api",
            last_checked_at=NOW - timedelta(hours=6),
            issues=[],
        )
    )


def _seed_health_and_findings(database: Session, index: int, spec: dict) -> None:
    """Attach one health check plus that client's findings and tasks."""
    findings = _findings_for(spec["id"], spec["business_name"])
    if not findings:
        return

    open_count = sum(1 for item in findings if item["status"] == "open")
    check = models.HealthCheck(
        id=f"demo-hc-{index:04d}",
        client_id=spec["id"],
        overall_status="attention" if open_count else "healthy",
        website_status="ok" if spec["website"] else "unknown",
        summary=(
            f"{open_count} open finding(s) across website and profile checks."
            if open_count
            else "No open findings on the most recent check."
        ),
        checked_at=NOW - timedelta(hours=8),
    )
    database.add(check)

    created_findings = []
    for position, item in enumerate(findings):
        finding = models.Finding(
            id=f"demo-fd-{index:02d}{position:02d}",
            client_id=spec["id"],
            rule_key=item["rule_key"],
            title=item["title"],
            explanation=item["explanation"],
            evidence={
                "source": item["source"],
                "observed_at": (NOW - timedelta(hours=8)).isoformat(),
                "sample": "Fabricated demo evidence.",
            },
            source=item["source"],
            severity=item["severity"],
            confidence=item["confidence"],
            recommended_action=item["recommended_action"],
            status=item["status"],
            discovered_at=NOW - timedelta(days=14 - position),
            last_seen_at=NOW - timedelta(hours=8),
            occurrence_count=3 - position if position < 3 else 1,
        )
        database.add(finding)
        created_findings.append(finding)

    database.flush()

    tasks = _tasks_for(spec["id"])
    for position, item in enumerate(tasks):
        source = created_findings[min(position, len(created_findings) - 1)]
        database.add(
            models.Task(
                id=f"demo-tk-{index:02d}{position:02d}",
                client_id=spec["id"],
                source_finding_id=source.id,
                title=item["title"],
                requested_outcome=item["requested_outcome"],
                reason=item["reason"],
                expected_result=item["expected_result"],
                success_metric=item["success_metric"],
                verification_window="Verify in the next reporting cycle.",
                estimated_effort=item["estimated_effort"],
                risk=item["risk"],
                required_access=item["required_access"],
                status=item["status"],
                proposed_at=NOW - timedelta(days=10 - position),
            )
        )


def _seed_metrics(database: Session, index: int, spec: dict) -> None:
    """Record a few months of invented but internally consistent metrics."""
    if spec["search_console"] == "unavailable":
        # An unavailable provider must show as absent data, never as zero.
        return

    base_calls = 18 + index * 6
    base_impressions = 900 + index * 220
    for offset, period in enumerate(["2026-06", "2026-07", "2026-08"]):
        growth = 1 + (offset * 0.14)
        database.add(
            models.MetricSnapshot(
                id=f"demo-ms-{index:02d}{offset:02d}a",
                client_id=spec["id"],
                metric_name="phone_calls",
                value=int(base_calls * growth),
                measurement_period=period,
                recorded_at=NOW - timedelta(days=(2 - offset) * 30),
                source_type="live_api",
            )
        )
        database.add(
            models.MetricSnapshot(
                id=f"demo-ms-{index:02d}{offset:02d}b",
                client_id=spec["id"],
                metric_name="search_impressions",
                value=int(base_impressions * growth),
                measurement_period=period,
                recorded_at=NOW - timedelta(days=(2 - offset) * 30),
                source_type="live_api",
            )
        )


def _seed_reports(database: Session, index: int, spec: dict) -> None:
    """Add one approved and one draft report so both states are visible."""
    if spec["profile"] != "official":
        return

    approved = models.Report(
        id=f"demo-rp-{index:04d}a",
        client_id=spec["id"],
        report_type="client",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        title=f"{spec['business_name']} — July summary",
        snapshot_data={
            "phone_calls": 18 + index * 6,
            "search_impressions": 900 + index * 220,
            "notes": "Fabricated demo figures.",
        },
        html_content=(
            "<h1>July summary</h1><p>Demo report content. Every figure on this "
            "page is invented for the public demo.</p>"
        ),
        generated_by="owner@demo-agency.example",
        generation_reason="scheduled",
        status="approved",
        approved_by="owner@demo-agency.example",
        approved_at=NOW - timedelta(days=20),
        created_at=NOW - timedelta(days=22),
    )
    database.add(approved)

    draft = models.Report(
        id=f"demo-rp-{index:04d}b",
        client_id=spec["id"],
        report_type="client",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        title=f"{spec['business_name']} — August summary",
        snapshot_data={
            "phone_calls": int((18 + index * 6) * 1.14),
            "search_impressions": int((900 + index * 220) * 1.14),
            "notes": "Fabricated demo figures.",
        },
        html_content=(
            "<h1>August summary</h1><p>Draft awaiting owner approval. Demo "
            "content only.</p>"
        ),
        generated_by="owner@demo-agency.example",
        generation_reason="scheduled",
        status="draft",
        created_at=NOW - timedelta(days=2),
    )
    database.add(draft)
