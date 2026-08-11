"""Phase 6 rules-based client health checks and findings."""

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_database
from app.health_rules import DECLINE_METRICS, ProposedFinding, evaluate_health
from app.notification_service import notify_health_finding

router = APIRouter(tags=["health checks"])
TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "health_check.html"


def require_client(database: Session, client_id: str) -> models.Client:
    client = database.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def latest_intake(database: Session, client_id: str):
    return database.scalar(
        select(models.Intake)
        .where(models.Intake.client_id == client_id)
        .order_by(models.Intake.submitted_at.desc(), models.Intake.id.desc())
    )


def metric_comparisons(database: Session, client_id: str) -> list[dict[str, Any]]:
    """Build prior/current comparisons from saved snapshots without changing them."""
    comparisons = []
    for metric_name in sorted(DECLINE_METRICS):
        snapshots = list(
            database.scalars(
                select(models.MetricSnapshot)
                .where(
                    models.MetricSnapshot.client_id == client_id,
                    models.MetricSnapshot.metric_name == metric_name,
                )
                .order_by(
                    models.MetricSnapshot.measurement_period,
                    models.MetricSnapshot.recorded_at,
                    models.MetricSnapshot.id,
                )
            )
        )
        latest_by_period = {}
        for snapshot in snapshots:
            latest_by_period[snapshot.measurement_period] = snapshot
        ordered = [latest_by_period[key] for key in sorted(latest_by_period)]
        if len(ordered) < 2:
            continue
        previous, current = ordered[-2:]
        previous_value = float(previous.value)
        current_value = float(current.value)
        percent = None if previous_value == 0 else round((current_value - previous_value) / previous_value * 100, 1)
        comparisons.append(
            {
                "metric_name": metric_name,
                "previous_period": previous.measurement_period,
                "previous_value": previous.value,
                "current_period": current.measurement_period,
                "current_value": current.value,
                "percent_change": percent,
                "source_type": current.source_type,
            }
        )
    return comparisons


def save_or_refresh_finding(
    database: Session,
    client_id: str,
    health_check_id: str,
    proposed: ProposedFinding,
) -> models.Finding:
    """Reuse one open finding while preserving every observation separately."""
    finding = database.scalar(
        select(models.Finding).where(
            models.Finding.client_id == client_id,
            models.Finding.rule_key == proposed.rule_key,
            models.Finding.status == "open",
        )
    )
    now = datetime.utcnow()
    if finding is None:
        finding = models.Finding(client_id=client_id, **proposed.__dict__)
        database.add(finding)
        database.flush()
    else:
        finding.explanation = proposed.explanation
        finding.evidence = proposed.evidence
        finding.source = proposed.source
        finding.severity = proposed.severity
        finding.confidence = proposed.confidence
        finding.recommended_action = proposed.recommended_action
        finding.last_seen_at = now
        finding.occurrence_count += 1

    database.add(
        models.FindingObservation(
            client_id=client_id,
            finding_id=finding.id,
            health_check_id=health_check_id,
            evidence=proposed.evidence,
        )
    )
    return finding


def run_health_check(
    database: Session,
    client_id: str,
    website_status: str,
) -> tuple[models.HealthCheck, list[models.Finding]]:
    require_client(database, client_id)
    intake = latest_intake(database, client_id)
    integrations = list(
        database.scalars(
            select(models.IntegrationConnection).where(models.IntegrationConnection.client_id == client_id)
        )
    )
    overall_status, summary, proposed_findings = evaluate_health(
        website_status=website_status,
        intake_domain=intake.domain if intake else "",
        has_intake=intake is not None,
        integrations=[
            {
                "id": item.id,
                "integration_name": item.integration_name,
                "connection_status": item.connection_status,
                "issues": item.issues,
            }
            for item in integrations
        ],
        metric_comparisons=metric_comparisons(database, client_id),
    )
    check = models.HealthCheck(
        client_id=client_id,
        overall_status=overall_status,
        website_status=website_status,
        summary=summary,
    )
    database.add(check)
    database.flush()
    findings = [save_or_refresh_finding(database, client_id, check.id, item) for item in proposed_findings]
    for finding in findings:
        notify_health_finding(database, finding)
    database.commit()
    database.refresh(check)
    for finding in findings:
        database.refresh(finding)
    return check, findings


@router.post(
    "/clients/{client_id}/health-checks",
    response_model=schemas.HealthCheckRead,
    status_code=status.HTTP_201_CREATED,
)
def create_health_check(
    client_id: str,
    request: schemas.HealthCheckCreate,
    database: Session = Depends(get_database),
) -> dict:
    check, findings = run_health_check(database, client_id, request.website_status)
    return {**check.__dict__, "findings": findings}


@router.get("/clients/{client_id}/health-checks", response_model=list[schemas.HealthCheckRead])
def list_health_checks(client_id: str, database: Session = Depends(get_database)) -> list[dict]:
    require_client(database, client_id)
    checks = list(
        database.scalars(
            select(models.HealthCheck)
            .where(models.HealthCheck.client_id == client_id)
            .order_by(models.HealthCheck.checked_at.desc(), models.HealthCheck.id.desc())
        )
    )
    output = []
    for check in checks:
        finding_ids = list(
            database.scalars(
                select(models.FindingObservation.finding_id).where(
                    models.FindingObservation.client_id == client_id,
                    models.FindingObservation.health_check_id == check.id,
                )
            )
        )
        findings = list(database.scalars(select(models.Finding).where(models.Finding.id.in_(finding_ids)))) if finding_ids else []
        output.append({**check.__dict__, "findings": findings})
    return output


@router.get("/clients/{client_id}/findings", response_model=list[schemas.FindingRead])
def list_findings(client_id: str, database: Session = Depends(get_database)) -> list[models.Finding]:
    require_client(database, client_id)
    return list(
        database.scalars(
            select(models.Finding)
            .where(models.Finding.client_id == client_id)
            .order_by(models.Finding.discovered_at.desc(), models.Finding.id.desc())
        )
    )


def render_finding(finding: models.Finding) -> str:
    evidence = " · ".join(f"{key.replace('_', ' ')}: {value}" for key, value in finding.evidence.items())
    return f"""
      <article class="health-finding severity-{escape(finding.severity)}">
        <div class="finding-heading"><span>{escape(finding.severity.replace('_', ' ').title())}</span><small>{escape(finding.confidence)} confidence</small></div>
        <h3>{escape(finding.title)}</h3>
        <p>{escape(finding.explanation)}</p>
        <dl><div><dt>Evidence</dt><dd>{escape(evidence)}</dd></div><div><dt>Source</dt><dd>{escape(finding.source)}</dd></div><div><dt>Recommended action</dt><dd>{escape(finding.recommended_action)}</dd></div></dl>
        <footer>Open · first seen {finding.discovered_at.strftime('%b %d, %Y')} · seen {finding.occurrence_count} time{'s' if finding.occurrence_count != 1 else ''}</footer>
      </article>
    """


@router.get("/dashboard/clients/{client_id}/health", response_class=HTMLResponse)
def health_page(client_id: str, database: Session = Depends(get_database), saved: int = 0) -> HTMLResponse:
    client = require_client(database, client_id)
    latest_check = database.scalar(
        select(models.HealthCheck)
        .where(models.HealthCheck.client_id == client_id)
        .order_by(models.HealthCheck.checked_at.desc(), models.HealthCheck.id.desc())
    )
    findings = list_findings(client_id, database)
    open_findings = [finding for finding in findings if finding.status == "open"]
    status_name = latest_check.overall_status if latest_check else "not_enough_data"
    summary = latest_check.summary if latest_check else "Run the first check to evaluate the saved evidence."
    notice = '<p class="form-notice success-notice">Health check saved. No task was created.</p>' if saved else ""
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = (
        page.replace("{{BUSINESS_NAME}}", escape(client.business_name))
        .replace("{{CLIENT_ID}}", escape(client.id))
        .replace("{{STATUS_CLASS}}", escape(status_name))
        .replace("{{STATUS_LABEL}}", escape(status_name.replace("_", " ").title()))
        .replace("{{SUMMARY}}", escape(summary))
        .replace("{{CHECKED_AT}}", latest_check.checked_at.strftime("%b %d, %Y at %I:%M %p") if latest_check else "Not checked yet")
        .replace("{{FINDING_COUNT}}", str(len(open_findings)))
        .replace("{{FINDINGS}}", "".join(render_finding(item) for item in open_findings) or '<p class="health-empty">Healthy — no action needed.</p>')
        .replace("{{NOTICE}}", notice)
    )
    return HTMLResponse(page)


@router.post("/dashboard/clients/{client_id}/health/run", response_class=RedirectResponse)
async def health_page_run(
    client_id: str,
    request: Request,
    database: Session = Depends(get_database),
) -> RedirectResponse:
    encoded_values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    values = {key: entries[-1] for key, entries in encoded_values.items()}
    website_status = str(values.get("website_status", "unknown"))
    if website_status not in {"available", "unavailable", "unknown"}:
        raise HTTPException(status_code=422, detail="Invalid website status")
    run_health_check(database, client_id, website_status)
    return RedirectResponse(url=f"/dashboard/clients/{client_id}/health?saved=1", status_code=303)
