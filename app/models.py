"""SQLAlchemy models belong here.

Define tables and relationships in this file.
"""

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def make_client_id() -> str:
    """Create a short human-readable client ID."""
    return f"client_{uuid4().hex[:8]}"


def make_intake_id() -> str:
    """Create a short human-readable intake ID."""
    return f"intake_{uuid4().hex[:8]}"


def make_client_asset_id() -> str:
    """Create an ID for one client-owned approved asset reference."""
    return f"asset_{uuid4().hex[:8]}"


def make_interpretation_id() -> str:
    """Create an ID for one saved onboarding interpretation proposal."""
    return f"proposal_{uuid4().hex[:8]}"


def make_profile_version_id() -> str:
    """Create an ID for one reviewable profile version."""
    return f"profile_version_{uuid4().hex[:8]}"


def make_official_profile_id() -> str:
    """Create an ID for one approved official client profile."""
    return f"profile_{uuid4().hex[:8]}"


def make_integration_id() -> str:
    """Create an ID for one client data-source connection."""
    return f"integration_{uuid4().hex[:8]}"


def make_metric_id() -> str:
    """Create an ID for one permanent metric observation."""
    return f"metric_{uuid4().hex[:8]}"


def make_health_check_id() -> str:
    """Create an ID for one permanent health-check run."""
    return f"check_{uuid4().hex[:8]}"


def make_finding_id() -> str:
    """Create an ID for one issue that can be seen more than once."""
    return f"finding_{uuid4().hex[:8]}"


def make_observation_id() -> str:
    """Create an ID for one immutable observation of a finding."""
    return f"observation_{uuid4().hex[:8]}"


def make_task_id() -> str:
    """Create an ID for one proposed unit of client work."""
    return f"task_{uuid4().hex[:8]}"


def make_task_event_id() -> str:
    """Create an ID for one permanent task-history event."""
    return f"task_event_{uuid4().hex[:8]}"


def make_task_decision_id() -> str:
    """Create an ID for one permanent approval or rejection."""
    return f"decision_{uuid4().hex[:8]}"


def make_execution_id() -> str:
    """Create an ID for one permanent simulated execution result."""
    return f"execution_{uuid4().hex[:8]}"


def make_verification_id() -> str:
    """Create an ID for one permanent human verification decision."""
    return f"verification_{uuid4().hex[:8]}"


def make_outcome_measurement_id() -> str:
    """Create an id for one durable post-fulfillment outcome measurement."""
    return f"outcome_{uuid4().hex[:10]}"


def make_agency_member_id() -> str:
    """Create an ID for one agency team member."""
    return f"member_{uuid4().hex[:10]}"


def make_content_review_id() -> str:
    """Create an ID for one human content-quality review."""
    return f"content_review_{uuid4().hex[:10]}"


def make_report_id() -> str:
    """Create an ID for one immutable report snapshot."""
    return f"report_{uuid4().hex[:8]}"


def make_notification_id() -> str:
    """Create an ID for one meaningful internal notification."""
    return f"notification_{uuid4().hex[:8]}"


def make_slack_channel_connection_id() -> str:
    """Create an ID for one verified client-to-Slack-channel mapping."""
    return f"slack_channel_{uuid4().hex[:8]}"


def make_slack_delivery_id() -> str:
    """Create an ID for one audited Slack delivery attempt group."""
    return f"slack_delivery_{uuid4().hex[:8]}"


def make_report_delivery_id() -> str:
    """Create an ID for one audited client-report delivery attempt group."""
    return f"report_delivery_{uuid4().hex[:8]}"


def make_website_connection_id() -> str:
    """Create an ID for one client-to-website connection."""
    return f"website_{uuid4().hex[:8]}"


def make_website_metric_id() -> str:
    """Create an ID for one immutable website-analytics snapshot."""
    return f"webmetric_{uuid4().hex[:8]}"


def make_scheduled_job_id() -> str:
    """Create an ID for one repeatable background job."""
    return f"job_{uuid4().hex[:8]}"


def make_audit_event_id() -> str:
    return f"audit_{uuid4().hex[:10]}"


def make_google_oauth_state_id() -> str:
    """Create an ID for one short-lived Google OAuth handshake."""
    return f"google_oauth_{uuid4().hex[:10]}"


def make_codex_work_packet_id() -> str:
    """Create an ID for one saved, copyable Codex work packet."""
    return f"packet_{uuid4().hex[:10]}"


def make_website_preview_id() -> str:
    return f"preview_{uuid4().hex[:12]}"


def make_github_repository_connection_id() -> str:
    """Create an ID for one verified client-to-GitHub-repository mapping."""
    return f"github_repo_{uuid4().hex[:10]}"


def make_search_console_connection_id() -> str:
    """Create an ID for one client-bound Search Console property mapping."""
    return f"search_console_{uuid4().hex[:10]}"


def make_ai_usage_id() -> str:
    return f"ai_usage_{uuid4().hex[:10]}"


def make_onboarding_run_id() -> str:
    return f"onboarding_run_{uuid4().hex[:10]}"


def make_connection_candidate_id() -> str:
    return f"candidate_{uuid4().hex[:10]}"


def make_analytics_connection_id() -> str:
    return f"analytics_{uuid4().hex[:10]}"


def make_owner_session_id() -> str:
    return f"owner_session_{uuid4().hex[:12]}"


def make_slack_action_receipt_id() -> str:
    return f"slack_action_{uuid4().hex[:12]}"


def make_slack_conversation_turn_id() -> str:
    return f"slack_turn_{uuid4().hex[:12]}"


def make_slack_memory_id() -> str:
    return f"slack_memory_{uuid4().hex[:12]}"


def make_subscription_id() -> str:
    return f"subscription_{uuid4().hex[:12]}"


def make_subscription_event_id() -> str:
    return f"subscription_event_{uuid4().hex[:12]}"


def make_daily_plan_id() -> str:
    return f"daily_plan_{uuid4().hex[:12]}"


def make_gbp_connection_id() -> str:
    return f"gbp_connection_{uuid4().hex[:10]}"


def make_gbp_post_id() -> str:
    return f"gbp_post_{uuid4().hex[:10]}"


def make_prompt_artifact_id() -> str:
    return f"prompt_artifact_{uuid4().hex[:12]}"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=make_client_id)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    service_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="onboarding")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ClientSubscription(Base):
    """Provider-neutral commercial state for one client entitlement."""

    __tablename__ = "client_subscriptions"
    __table_args__ = (UniqueConstraint("client_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_subscription_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="trial")
    plan: Mapped[str] = mapped_column(String(80), nullable=False, default="agency")
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    provider_customer_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    provider_subscription_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SubscriptionEvent(Base):
    """Idempotency and audit record for one signed billing-provider event."""

    __tablename__ = "subscription_events"
    __table_args__ = (UniqueConstraint("event_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_subscription_event_id)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    client_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Intake(Base):
    __tablename__ = "intakes"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=make_intake_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    brand_colors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    business_hours: Mapped[str] = mapped_column(String(500), nullable=False)
    service_areas: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    google_business_profile: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled_workflows: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="received")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ClientAsset(Base):
    """A client-owned reference to an approved image, video, or document.

    Max stores the reference and ownership now. Uploading binary files to a
    storage provider remains a separate, explicitly connected step.
    """

    __tablename__ = "client_assets"
    __table_args__ = (UniqueConstraint("client_id", "reference"),)

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_client_asset_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(2000), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_reference")
    added_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class InterpretationProposal(Base):
    """A replaceable interpreter's proposal; it never replaces the source intake."""

    __tablename__ = "interpretation_proposals"
    __table_args__ = (UniqueConstraint("intake_id"),)

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_interpretation_id)
    intake_id: Mapped[str] = mapped_column(ForeignKey("intakes.id"), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    profile_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    conflicting_information: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ProfileVersion(Base):
    """Immutable review version derived from one interpretation proposal."""

    __tablename__ = "profile_versions"
    __table_args__ = (UniqueConstraint("source_proposal_id", "version_number"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_profile_version_id)
    source_proposal_id: Mapped[str] = mapped_column(ForeignKey("interpretation_proposals.id"), nullable=False, index=True)
    intake_id: Mapped[str] = mapped_column(ForeignKey("intakes.id"), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(nullable=False)
    profile_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decision_maker: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(String(1200), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class OfficialProfile(Base):
    """The one client profile that has passed human approval."""

    __tablename__ = "official_profiles"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_official_profile_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, unique=True, index=True)
    approved_version_id: Mapped[str] = mapped_column(ForeignKey("profile_versions.id"), nullable=False)
    profile_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class IntegrationConnection(Base):
    """Current connection information for one client data source."""

    __tablename__ = "integration_connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_integration_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    integration_name: Mapped[str] = mapped_column(String(120), nullable=False)
    connection_status: Mapped[str] = mapped_column(String(40), nullable=False)
    data_source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    issues: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class MetricSnapshot(Base):
    """One immutable metric value observed for exactly one client."""

    __tablename__ = "metric_snapshots"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_metric_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    measurement_period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class HealthCheck(Base):
    """One permanent, explainable health evaluation for exactly one client."""

    __tablename__ = "health_checks"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_health_check_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    overall_status: Mapped[str] = mapped_column(String(30), nullable=False)
    website_status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Finding(Base):
    """The current lifecycle record for one client issue."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_finding_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    rule_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    occurrence_count: Mapped[int] = mapped_column(nullable=False, default=1)


class FindingObservation(Base):
    """Immutable evidence showing that one check detected one finding."""

    __tablename__ = "finding_observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_observation_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), nullable=False, index=True)
    health_check_id: Mapped[str] = mapped_column(ForeignKey("health_checks.id"), nullable=False, index=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Task(Base):
    """One proposed unit of work tied to an evidence-backed finding."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_task_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    source_finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_outcome: Mapped[str] = mapped_column(String(1200), nullable=False)
    reason: Mapped[str] = mapped_column(String(1200), nullable=False)
    expected_result: Mapped[str] = mapped_column(
        String(1200),
        nullable=False,
        default="Verify the requested outcome with source evidence.",
        server_default="Verify the requested outcome with source evidence.",
    )
    success_metric: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="The source-specific metric named in the evidence.",
        server_default="The source-specific metric named in the evidence.",
    )
    verification_window: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        default="Verify in the next reporting cycle.",
        server_default="Verify in the next reporting cycle.",
    )
    estimated_effort: Mapped[str] = mapped_column(String(120), nullable=False)
    risk: Mapped[str] = mapped_column(String(30), nullable=False)
    required_access: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    browser_control_approved_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    browser_control_approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    browser_control_approval_reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    proposed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class TaskDependency(Base):
    """A task that must be verified before another task becomes ready."""

    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("task_id", "depends_on_task_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    depends_on_task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)


class TaskDecision(Base):
    """Immutable agency-owner approval or rejection information."""

    __tablename__ = "task_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_task_decision_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_maker: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class TaskStatusEvent(Base):
    """Immutable evidence of every task-state change."""

    __tablename__ = "task_status_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_task_event_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class FulfillmentExecution(Base):
    """One permanent simulator, Codex-handoff, website, or browser execution."""

    __tablename__ = "fulfillment_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_execution_id)
    operation_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    intended_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    simulated_changed_files: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    simulated_test_results: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False)
    attempt_count: Mapped[int] = mapped_column(nullable=False)
    retry_delays_seconds: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    failure_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ExecutionVerification(Base):
    """One immutable human decision about one completed execution."""

    __tablename__ = "execution_verifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_verification_id)
    decision_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("fulfillment_executions.id"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(String(1200), nullable=False)
    review_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confirmations: Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_results: Mapped[dict] = mapped_column(JSON, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class OutcomeMeasurement(Base):
    """A source-backed measurement of whether completed work produced its target outcome."""

    __tablename__ = "outcome_measurements"
    __table_args__ = (UniqueConstraint("operation_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_outcome_measurement_id)
    operation_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    execution_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("fulfillment_executions.id"), nullable=True, index=True
    )
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    baseline_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    assessment: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    notes: Mapped[str] = mapped_column(String(1200), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Report(Base):
    """One immutable internal or client-facing report awaiting approval."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_report_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    snapshot_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generation_reason: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    client_share_issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    client_share_revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ReportDelivery(Base):
    """One retry-safe delivery of an approved client report."""

    __tablename__ = "report_deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_report_delivery_id)
    operation_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.id"), nullable=False, unique=True, index=True
    )
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    channel_connection_id: Mapped[str] = mapped_column(
        ForeignKey("slack_channel_connections.id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    message_timestamp: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Notification(Base):
    """One actionable event delivered to Max's internal notification inbox."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_notification_id)
    event_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    importance: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[str] = mapped_column(String(600), nullable=False)
    requested_action: Mapped[str] = mapped_column(String(600), nullable=False)
    related_record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    related_record_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SlackChannelConnection(Base):
    """One verified public Slack channel belonging to exactly one Max client."""

    __tablename__ = "slack_channel_connections"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=make_slack_channel_connection_id
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    workspace_name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    channel_name: Mapped[str] = mapped_column(String(80), nullable=False)
    connection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="connected")
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class SlackDelivery(Base):
    """One idempotent delivery record for one saved Max notification."""

    __tablename__ = "slack_deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_slack_delivery_id)
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.id"), nullable=False, unique=True, index=True
    )
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    channel_connection_id: Mapped[str] = mapped_column(
        ForeignKey("slack_channel_connections.id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    message_timestamp: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class WebsiteConnection(Base):
    """One verified hosting project and production website for one client."""

    __tablename__ = "website_connections"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_website_connection_id)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    external_project_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    production_url: Mapped[str] = mapped_column(String(500), nullable=False)
    connection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="linked")
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class GitHubRepositoryConnection(Base):
    """One repository assigned to exactly one client for scoped work packets."""

    __tablename__ = "github_repository_connections"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=make_github_repository_connection_id
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    repository_name: Mapped[str] = mapped_column(String(200), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    default_branch: Mapped[str] = mapped_column(String(200), nullable=False, default="main")
    connection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="linked")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class SearchConsoleConnection(Base):
    """One verified Search Console property explicitly assigned to one client."""

    __tablename__ = "search_console_connections"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=make_search_console_connection_id
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    property_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    connection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="linked")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_successful_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    last_query_rows: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    last_page_rows: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    last_query_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_query_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class GoogleBusinessProfileConnection(Base):
    """One client-bound Google Business Profile location reference."""

    __tablename__ = "google_business_profile_connections"
    __table_args__ = (UniqueConstraint("account_id", "location_id"),)

    id: Mapped[str] = mapped_column(String(34), primary_key=True, default=make_gbp_connection_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, unique=True, index=True)
    account_id: Mapped[str] = mapped_column(String(120), nullable=False)
    location_id: Mapped[str] = mapped_column(String(160), nullable=False)
    location_name: Mapped[str] = mapped_column(String(300), nullable=False)
    connection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="connected")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class GoogleBusinessProfilePost(Base):
    """An approval-gated Google Business Profile post."""

    __tablename__ = "google_business_profile_posts"

    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=make_gbp_post_id)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("google_business_profile_connections.id"), nullable=False)
    summary: Mapped[str] = mapped_column(String(1500), nullable=False)
    call_to_action_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    external_post_id: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AIUsageRecord(Base):
    """One immutable, idempotent estimate or actual AI-use record."""

    __tablename__ = "ai_usage_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_ai_usage_id)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    client_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    model_role: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    actual_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class PromptArtifact(Base):
    """Immutable record of the versioned context used for one AI operation."""

    __tablename__ = "prompt_artifacts"
    __table_args__ = (UniqueConstraint("operation_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_prompt_artifact_id)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    intake_id: Mapped[Optional[str]] = mapped_column(ForeignKey("intakes.id"), nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_role: Mapped[str] = mapped_column(String(40), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    knowledge_files: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class CodexWorkPacket(Base):
    """A safe, time-limited handoff packet for an approved client task.

    The packet records context and authorization state only. It never performs
    GitHub, Vercel, or Codex work on its own.
    """

    __tablename__ = "codex_work_packets"

    id: Mapped[str] = mapped_column(String(28), primary_key=True, default=make_codex_work_packet_id)
    operation_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="generated")
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    repository_owner: Mapped[str] = mapped_column(String(200), nullable=False)
    repository_name: Mapped[str] = mapped_column(String(200), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    branch: Mapped[str] = mapped_column(String(200), nullable=False)
    vercel_project_id: Mapped[str] = mapped_column(String(80), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    prohibited_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    publishing_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    packet_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    handed_off_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    handed_off_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    result_execution_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("fulfillment_executions.id"), nullable=True, unique=True, index=True
    )


class ContentReview(Base):
    """Human-writing and factual review for Codex local-page/blog output."""

    __tablename__ = "content_reviews"
    __table_args__ = (UniqueConstraint("packet_id"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=make_content_review_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    packet_id: Mapped[str] = mapped_column(ForeignKey("codex_work_packets.id"), nullable=False, unique=True, index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("fulfillment_executions.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    checklist: Mapped[dict] = mapped_column(JSON, nullable=False)
    notes: Mapped[str] = mapped_column(String(2000), nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class WebsitePreview(Base):
    """Immutable generated website proposal held for review before execution."""

    __tablename__ = "website_previews"
    __table_args__ = (UniqueConstraint("operation_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_website_preview_id)
    operation_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    packet_id: Mapped[str] = mapped_column(ForeignKey("codex_work_packets.id"), nullable=False, index=True)
    model_role: Mapped[str] = mapped_column(String(40), nullable=False)
    files: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    file_manifest: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    comparison: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    technical_audit: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class WebsiteMetricSnapshot(Base):
    """One aggregate tracker result for exactly one client and date window."""

    __tablename__ = "website_metric_snapshots"
    __table_args__ = (
        UniqueConstraint("client_id", "window_days", "period_end", "source"),
    )

    id: Mapped[str] = mapped_column(String(28), primary_key=True, default=make_website_metric_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    window_days: Mapped[int] = mapped_column(nullable=False)
    unique_visitors: Mapped[int] = mapped_column(nullable=False)
    pageviews: Mapped[int] = mapped_column(nullable=False)
    call_clicks: Mapped[int] = mapped_column(nullable=False)
    form_submits: Mapped[int] = mapped_column(nullable=False)
    tracker_sites: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class WebsiteAnalyticsConnection(Base):
    """Verified tracker identifiers assigned to exactly one client."""

    __tablename__ = "website_analytics_connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_analytics_connection_id)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    tracker_sites: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    connection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="connected")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="auto_discovery")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class OnboardingAutomationRun(Base):
    """Durable, resumable state for one immutable intake's automation."""

    __tablename__ = "onboarding_automation_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_onboarding_run_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    intake_id: Mapped[str] = mapped_column(
        ForeignKey("intakes.id"), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    current_step: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    steps: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=3)
    last_error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConnectionCandidate(Base):
    """A provider match that requires an explicit agency-owner decision."""

    __tablename__ = "connection_candidates"
    __table_args__ = (UniqueConstraint("run_id", "provider", "external_identifier"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_connection_candidate_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("onboarding_automation_runs.id"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    connection_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    match_evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    match_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="uncertain")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ScheduledJob(Base):
    """A persisted job definition whose runs are safe to repeat."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (UniqueConstraint("job_key"),)

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=make_scheduled_job_id)
    job_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    client_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    interval_minutes: Mapped[int] = mapped_column(nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    last_error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(nullable=False, default=0)
    last_duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditEvent(Base):
    """Append-only security and decision audit record."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(28), primary_key=True, default=make_audit_event_id)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    client_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    record_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    record_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class GoogleOAuthState(Base):
    """One-time, short-lived state value used to protect the Google setup flow.

    The OAuth access and refresh tokens are deliberately not stored here. The
    callback displays the refresh token once so the owner can place it in the
    hosting provider's encrypted environment settings.
    """

    __tablename__ = "google_oauth_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=make_google_oauth_state_id)
    state_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    scopes: Mapped[str] = mapped_column(String(1000), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default="integration_setup")
    nonce_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    redirect_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class OwnerSession(Base):
    """Opaque, revocable owner session; the browser stores only the raw token."""

    __tablename__ = "owner_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_owner_session_id)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AgencyMember(Base):
    """Durable agency identity and least-privilege role mapping."""

    __tablename__ = "agency_members"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_agency_member_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="operator", index=True)
    slack_user_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SlackActionReceipt(Base):
    """One idempotent record for one signed Slack interaction payload."""

    __tablename__ = "slack_action_receipts"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=make_slack_action_receipt_id
    )
    action_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    slack_user_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(String(80), nullable=False)
    related_record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    related_record_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    result_status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class SlackConversationTurn(Base):
    """Redacted, bounded conversation memory for follow-up questions in Slack."""

    __tablename__ = "slack_conversation_turns"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_slack_conversation_turn_id)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    thread_ts: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    slack_user_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    client_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    result_status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class SlackMemory(Base):
    """One explicit, durable agency- or client-scoped Slack memory."""

    __tablename__ = "slack_memories"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_slack_memory_id)
    workspace_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    client_id: Mapped[Optional[str]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    memory_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="general", index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(40), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), index=True
    )


class DailyClientPlan(Base):
    """One refreshable evidence-backed work plan for one client and day."""

    __tablename__ = "daily_client_plans"
    __table_args__ = (UniqueConstraint("client_id", "plan_date"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=make_daily_plan_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    depth: Mapped[str] = mapped_column(String(20), nullable=False, default="simple")
    focus: Mapped[str] = mapped_column(String(30), nullable=False, default="all")
    items: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    source_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), index=True
    )
