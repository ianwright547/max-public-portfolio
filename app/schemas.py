"""Pydantic schemas belong here.

Keep request and response shapes separate from database models.
"""

from datetime import date, datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClientCreate(BaseModel):
    """Incoming payload for creating a client."""

    model_config = ConfigDict(str_strip_whitespace=True)

    business_name: str = Field(min_length=1, max_length=200)
    service_start_date: date


class PromptCompileRequest(BaseModel):
    operation_key: str = Field(min_length=1, max_length=160)
    purpose: Literal[
        "onboarding_interpretation",
        "fulfillment_plan",
        "website_generation",
        "website_audit",
        "gbp_draft",
        "reporting",
    ]
    model_role: str = Field(default="balanced", min_length=1, max_length=40)
    intake_id: Optional[str] = None
    task_id: Optional[str] = None


class PromptArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    client_id: str
    intake_id: Optional[str]
    task_id: Optional[str]
    purpose: str
    prompt_version: str
    model_role: str
    input_snapshot: dict
    knowledge_files: list[str]
    system_prompt: str
    user_prompt: str
    content_hash: str
    created_at: datetime


class ClientUpdate(BaseModel):
    """Basic editable client information; omitted fields remain unchanged."""

    model_config = ConfigDict(str_strip_whitespace=True)

    business_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    service_start_date: Optional[date] = None


class ClientRead(ClientCreate):
    """Response payload for a client."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    archived_at: Optional[datetime] = None


class AgencyMemberCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    role: Literal["owner", "admin", "operator", "viewer"] = "operator"
    slack_user_id: Optional[str] = Field(default=None, min_length=1, max_length=40)


class AgencyMemberUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    role: Optional[Literal["owner", "admin", "operator", "viewer"]] = None
    slack_user_id: Optional[str] = Field(default=None, min_length=1, max_length=40)
    active: Optional[bool] = None


class AgencyMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    role: str
    slack_user_id: Optional[str]
    active: bool
    created_at: datetime
    updated_at: datetime


class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: Literal["trial", "active", "past_due", "paused", "cancelled", "incomplete"]
    plan: str = Field(default="agency", min_length=1, max_length=80)
    provider: str = Field(default="manual", min_length=1, max_length=40)
    provider_customer_id: Optional[str] = Field(default=None, max_length=160)
    provider_subscription_id: Optional[str] = Field(default=None, max_length=160)
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SubscriptionRead(SubscriptionUpdate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    created_at: datetime
    updated_at: datetime


class BillingWebhookEvent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=160)
    event_type: str = Field(min_length=1, max_length=80)
    client_id: str = Field(min_length=1, max_length=16)
    provider: str = Field(min_length=1, max_length=40)
    status: Literal["trial", "active", "past_due", "paused", "cancelled", "incomplete"]
    plan: str = Field(default="agency", min_length=1, max_length=80)
    provider_customer_id: Optional[str] = Field(default=None, max_length=160)
    provider_subscription_id: Optional[str] = Field(default=None, max_length=160)
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False


class IntakeCreate(BaseModel):
    """Incoming onboarding form payload."""

    model_config = ConfigDict(str_strip_whitespace=True)

    phone_number: str = Field(min_length=1, max_length=50)
    email: EmailStr
    brand_colors: list[str] = Field(min_length=1)
    domain: str = Field(min_length=1, max_length=255)
    business_hours: str = Field(min_length=1, max_length=500)
    service_areas: list[str] = Field(min_length=1)
    google_business_profile: str = Field(min_length=1, max_length=500)
    enabled_workflows: list[str] = Field(min_length=1)


class IntakeRead(IntakeCreate):
    """Response payload for a saved onboarding form."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    status: str
    submitted_at: datetime


class InterpretationRead(BaseModel):
    """A proposed profile that remains separate from the original intake."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    intake_id: str
    client_id: str
    profile_data: dict
    missing_information: list[str]
    conflicting_information: list[str]
    processing_status: str
    processed_at: datetime


class ProfileVersionRead(BaseModel):
    """One immutable profile version and its human decision."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_proposal_id: str
    intake_id: str
    client_id: str
    version_number: int
    profile_data: dict
    status: str
    decision_maker: Optional[str]
    decision_reason: Optional[str]
    decided_at: Optional[datetime]


class ProfileDecision(BaseModel):
    decision: Literal["approve", "reject"]
    decision_maker: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=1200)


class ProfileCorrection(BaseModel):
    decision_maker: str = Field(min_length=1, max_length=200)
    profile_data: dict


class OfficialProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    approved_version_id: str
    profile_data: dict
    approved_by: str
    approved_at: datetime


class IntegrationRead(BaseModel):
    """Response describing one client data source."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    integration_name: str
    connection_status: str
    data_source_type: str
    last_checked_at: Optional[datetime]
    issues: list[str]


class MetricCreate(BaseModel):
    """Manual or imported metric information accepted by the public API."""

    model_config = ConfigDict(str_strip_whitespace=True)

    metric_name: str = Field(min_length=1, max_length=60)
    value: Union[int, float, str]
    measurement_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    source_type: Literal["manual", "imported"] = "manual"
    is_baseline: bool = False


class MockMetricRequest(BaseModel):
    """Request for deterministic sample data that is always labeled mock."""

    measurement_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    mark_as_baseline: bool = False


class MetricRead(BaseModel):
    """Response for one saved historical metric snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    metric_name: str
    value: Any
    measurement_period: str
    recorded_at: datetime
    source_type: str
    is_baseline: bool


class MetricChange(BaseModel):
    """Calculated difference between two saved metric snapshots."""

    amount: float
    percent: Optional[float]
    unit: str


class MetricComparison(BaseModel):
    """Current result compared with its baseline and previous period."""

    client_id: str
    metric_name: str
    current: MetricRead
    baseline: Optional[MetricRead]
    previous_period: Optional[MetricRead]
    change_from_baseline: Optional[MetricChange]
    change_from_previous: Optional[MetricChange]


class HealthCheckCreate(BaseModel):
    """Manual observation needed because Phase 6 does not contact websites."""

    website_status: Literal["available", "unavailable", "unknown"] = "unknown"


class FindingRead(BaseModel):
    """One explainable issue associated with exactly one client."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    title: str
    explanation: str
    evidence: dict[str, Any]
    source: str
    severity: str
    confidence: str
    recommended_action: str
    status: str
    discovered_at: datetime
    last_seen_at: datetime
    occurrence_count: int


class HealthCheckRead(BaseModel):
    """The saved result of one rules-based client health check."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    overall_status: str
    website_status: str
    summary: str
    checked_at: datetime
    findings: list[FindingRead]


class TaskCreate(BaseModel):
    """Information required to propose—not execute—one task."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_finding_id: str = Field(min_length=1, max_length=24)
    title: str = Field(min_length=1, max_length=200)
    requested_outcome: str = Field(min_length=1, max_length=1200)
    reason: str = Field(min_length=1, max_length=1200)
    expected_result: str = Field(default="Verify the requested outcome with source evidence.", max_length=1200)
    success_metric: str = Field(default="The source-specific metric named in the evidence.", max_length=500)
    verification_window: str = Field(default="Verify in the next reporting cycle.", max_length=300)
    estimated_effort: str = Field(min_length=1, max_length=120)
    risk: Literal["low", "medium", "high"]
    required_access: list[str] = Field(default_factory=list)
    dependency_ids: list[str] = Field(default_factory=list)


class TaskDecisionCreate(BaseModel):
    """An explicit human approval or rejection."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approved", "rejected"]
    decision_maker: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=1000)


class TaskStatusChange(BaseModel):
    """A requested state change after the approval decision."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_status: Literal["blocked", "ready", "running", "completed", "failed", "verified"]
    changed_by: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=1000)


class BrowserControlApprovalCreate(BaseModel):
    """Explicit, scoped owner approval for browser control on one task."""

    model_config = ConfigDict(str_strip_whitespace=True)

    approved_by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


class TaskDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    decision: str
    decision_maker: str
    reason: Optional[str]
    decided_at: datetime


class TaskRead(BaseModel):
    """A task plus the dependencies and permanent approval information."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    source_finding_id: str
    title: str
    requested_outcome: str
    reason: str
    expected_result: str
    success_metric: str
    verification_window: str
    estimated_effort: str
    risk: str
    required_access: list[str]
    browser_control_approved_by: Optional[str]
    browser_control_approved_at: Optional[datetime]
    browser_control_approval_reason: Optional[str]
    dependency_ids: list[str]
    status: str
    proposed_at: datetime
    approval_information: list[TaskDecisionRead]
    outcome_measurements: list["OutcomeMeasurementRead"] = Field(default_factory=list)


class OutcomeMeasurementCreate(BaseModel):
    """Record one source-backed result after a task's verification window."""

    model_config = ConfigDict(str_strip_whitespace=True)

    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    execution_id: Optional[str] = Field(default=None, max_length=40)
    metric_name: str = Field(min_length=1, max_length=200)
    baseline_value: Optional[float] = None
    observed_value: Optional[float] = None
    unit: Optional[str] = Field(default=None, max_length=80)
    assessment: Literal["met", "not_met", "inconclusive"]
    source_type: Literal["live_api", "manual", "imported", "mock"]
    source_reference: str = Field(min_length=1, max_length=500)
    evidence: list[str] = Field(min_length=1, max_length=20)
    notes: str = Field(min_length=1, max_length=1200)
    recorded_by: str = Field(min_length=1, max_length=200)
    observed_at: datetime


class OutcomeMeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    client_id: str
    task_id: str
    execution_id: Optional[str]
    metric_name: str
    baseline_value: Optional[float]
    observed_value: Optional[float]
    unit: Optional[str]
    assessment: str
    source_type: str
    source_reference: str
    evidence: list[str]
    notes: str
    recorded_by: str
    observed_at: datetime
    created_at: datetime
    reused_existing: bool = False


class SimulatedExecutionCreate(BaseModel):
    """Demo controls for one fake fulfillment run."""

    model_config = ConfigDict(str_strip_whitespace=True)

    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    outcome: Literal["success", "failure", "blocked"]
    failure_type: Optional[Literal["temporary", "permanent"]] = None
    temporary_failures_before_result: int = Field(default=0, ge=0, le=3)
    estimated_cost: float = Field(default=0.25, ge=0, le=10000)


class SimulatedExecutionRead(BaseModel):
    """The permanent result returned by the safe simulator."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    client_id: str
    task_id: str
    status: str
    intended_actions: list[str]
    simulated_changed_files: list[str]
    simulated_test_results: list[dict[str, Any]]
    evidence: dict[str, Any]
    estimated_cost: float
    attempt_count: int
    retry_delays_seconds: list[int]
    failure_type: Optional[str]
    error_message: Optional[str]
    started_at: datetime
    completed_at: datetime
    reused_existing: bool = False


class WebsiteFileChange(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1_000_000)


class WebsiteExecutionCreate(BaseModel):
    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    packet_id: str = Field(min_length=1, max_length=40)
    commit_message: str = Field(min_length=1, max_length=200)
    files: list[WebsiteFileChange] = Field(min_length=1, max_length=100)


class WebsiteRollbackCreate(BaseModel):
    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    reason: str = Field(min_length=1, max_length=1000)


class BrowserExecutionCreate(BaseModel):
    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    target_url: str = Field(pattern=r"^https://[^\s]+$", max_length=1000)
    instructions: str = Field(min_length=1, max_length=4000)
    estimated_cost: float = Field(default=0.0, ge=0, le=10000)


class WebsiteGenerationCreate(BaseModel):
    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    packet_id: str = Field(min_length=1, max_length=40)
    commit_message: str = Field(min_length=1, max_length=200)
    model_role: Literal["quality", "balanced"] = "quality"


class WebsitePreviewCreate(BaseModel):
    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    packet_id: str = Field(min_length=1, max_length=40)
    model_role: Literal["quality", "balanced"] = "quality"
    generated_by: str = Field(default="Agency Owner", min_length=1, max_length=200)


class WebsitePreviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    client_id: str
    task_id: str
    packet_id: str
    model_role: str
    files: list[dict[str, Any]]
    file_manifest: list[dict[str, Any]]
    comparison: dict[str, Any]
    technical_audit: dict[str, Any]
    status: str
    generated_by: str
    created_at: datetime


class ExecutionVerificationCreate(BaseModel):
    """One explicit human review of a completed execution."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    outcome: Literal[
        "verified",
        "verification_failed",
        "needs_manual_review",
        "not_enough_evidence",
    ]
    reviewer: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=1200)
    review_evidence: list[str] = Field(min_length=1)
    correct_client_confirmed: bool
    approved_task_followed: bool
    output_exists: bool
    result_matches_requested_outcome: bool
    no_unexpected_changes: bool


class ExecutionVerificationRead(BaseModel):
    """A saved review plus the checks Max evaluated."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    decision_key: str
    client_id: str
    task_id: str
    execution_id: str
    outcome: str
    reviewer: str
    explanation: str
    review_evidence: list[str]
    confirmations: dict[str, bool]
    validation_results: dict[str, bool]
    decided_at: datetime
    resolved_finding: bool = False
    reused_existing: bool = False


class ReportCreate(BaseModel):
    """The reporting period and audience selected by the agency owner."""

    model_config = ConfigDict(str_strip_whitespace=True)

    report_type: Literal["internal", "client"]
    period_start: date
    period_end: date
    generated_by: str = Field(min_length=1, max_length=200)
    generation_reason: Literal["manual", "scheduled"] = "manual"
    update_mode: Literal["saved", "simple", "in_depth"] = "saved"


class ReportRead(BaseModel):
    """Metadata and exact facts saved for one report version."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    report_type: str
    period_start: date
    period_end: date
    title: str
    snapshot_data: dict[str, Any]
    generated_by: str
    generation_reason: str
    status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    created_at: datetime


class ReportApprovalCreate(BaseModel):
    approved_by: str = Field(min_length=1, max_length=200)


class ReportPlanTaskCreate(BaseModel):
    """Convert one immutable report recommendation into a proposed task."""

    model_config = ConfigDict(str_strip_whitespace=True)

    created_by: str = Field(min_length=1, max_length=200)
    estimated_effort: str = Field(default="Needs scoping", min_length=1, max_length=120)
    risk: Literal["low", "medium", "high"] = "medium"
    required_access: list[str] = Field(default_factory=list)


class ReportDeliveryRead(BaseModel):
    """One audited, retry-safe delivery of an approved client report."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    report_id: str
    client_id: str
    channel_connection_id: str
    channel_id: str
    status: str
    message_timestamp: Optional[str]
    attempt_count: int
    last_error: Optional[str]
    last_attempt_at: Optional[datetime]
    delivered_at: Optional[datetime]
    created_at: datetime


class NotificationRead(BaseModel):
    """One actionable item in the internal notification inbox."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    category: str
    importance: str
    explanation: str
    requested_action: str
    related_record_type: str
    related_record_id: str
    created_at: datetime
    is_read: bool
    read_at: Optional[datetime]


class SlackChannelRead(BaseModel):
    """A verified one-client-to-one-channel Slack mapping."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    workspace_id: str
    workspace_name: str
    channel_id: str
    channel_name: str
    connection_status: str
    last_verified_at: datetime
    last_error: Optional[str]
    created_at: datetime


class SlackChannelConnectionResult(BaseModel):
    """Return whether Max created a channel or reused its verified mapping."""

    connection: SlackChannelRead
    created: bool


class SlackChannelRenameRequest(BaseModel):
    """Optional explicit display name for a mapped Slack channel."""

    channel_name: Optional[str] = Field(default=None, min_length=1, max_length=80)


class SlackDeliveryRead(BaseModel):
    """One audited Slack delivery result for one internal notification."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    notification_id: str
    client_id: str
    channel_connection_id: str
    channel_id: str
    status: str
    message_timestamp: Optional[str]
    attempt_count: int
    last_error: Optional[str]
    last_attempt_at: Optional[datetime]
    delivered_at: Optional[datetime]
    created_at: datetime


class WebsiteConnectionCreate(BaseModel):
    """A verified hosting-project link for one existing Max client."""

    model_config = ConfigDict(str_strip_whitespace=True)

    provider: Literal["vercel"] = "vercel"
    external_project_id: str = Field(min_length=1, max_length=80)
    project_name: str = Field(min_length=1, max_length=200)
    production_url: str = Field(pattern=r"^https://[^\s]+$", max_length=500)
    source: Literal["vercel_cli"] = "vercel_cli"


class WebsiteConnectionRead(WebsiteConnectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    connection_status: str
    source: str
    linked_at: datetime


class WebsiteConnectionSyncRead(BaseModel):
    client_id: str
    project_id: str
    connection_status: str
    last_checked_at: datetime
    issues: list[str]


class GitHubRepositoryConnectionCreate(BaseModel):
    """A client-bound GitHub repository reference; no GitHub credentials are stored."""

    model_config = ConfigDict(str_strip_whitespace=True)

    owner: str = Field(min_length=1, max_length=200)
    repository_name: str = Field(min_length=1, max_length=200)
    repository_url: str = Field(pattern=r"^https://github\.com/[^\s]+$", max_length=500)
    default_branch: str = Field(default="main", min_length=1, max_length=200)
    source: Literal["manual", "github_app"] = "manual"


class GitHubRepositoryConnectionRead(GitHubRepositoryConnectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    connection_status: str
    last_checked_at: Optional[datetime]
    last_verified_at: Optional[datetime]
    linked_at: datetime


class GitHubRepositoryVerificationRead(BaseModel):
    client_id: str
    repository_url: str
    connection_status: str
    last_checked_at: datetime
    issues: list[str]


class SearchConsoleConnectionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    property_url: str = Field(min_length=1, max_length=500)


class SearchConsoleConnectionRead(SearchConsoleConnectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    connection_status: str
    last_checked_at: Optional[datetime]
    last_successful_sync_at: Optional[datetime]
    last_error: Optional[str]
    last_query_rows: list[dict[str, Any]]
    last_page_rows: list[dict[str, Any]]
    last_query_start_date: Optional[date]
    last_query_end_date: Optional[date]
    linked_at: datetime


class SearchConsoleSyncRequest(BaseModel):
    start_date: date
    end_date: date
    mark_as_baseline: bool = False


class GoogleBusinessProfileConnectionCreate(BaseModel):
    account_id: str = Field(min_length=1, max_length=120)
    location_id: str = Field(min_length=1, max_length=160)
    location_name: str = Field(min_length=1, max_length=300)


class GoogleBusinessProfileConnectionRead(GoogleBusinessProfileConnectionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    connection_status: str
    last_checked_at: Optional[datetime]
    linked_at: datetime


class GoogleBusinessProfilePostCreate(BaseModel):
    operation_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    summary: str = Field(min_length=1, max_length=1500)
    call_to_action_url: Optional[str] = Field(default=None, max_length=1000)


class GoogleBusinessProfilePostApproval(BaseModel):
    approved_by: str = Field(min_length=1, max_length=200)


class GoogleBusinessProfilePostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    client_id: str
    connection_id: str
    summary: str
    call_to_action_url: Optional[str]
    status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    external_post_id: Optional[str]
    error_code: Optional[str]
    created_at: datetime
    published_at: Optional[datetime]


class AIUsageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    client_id: Optional[str]
    task_id: Optional[str]
    provider: str
    model: str
    model_role: str
    operation: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    estimated_cost_usd: float
    actual_cost_usd: Optional[float]
    created_at: datetime


class AIBudgetRead(BaseModel):
    month: str
    budget_usd: float
    used_usd: float
    remaining_usd: float
    status: str


class CodexWorkPacketCreate(BaseModel):
    """The repo and deployment target Max must verify before creating a packet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    operation_key: str = Field(min_length=1, max_length=120)
    created_by: str = Field(min_length=1, max_length=200)
    mode: Literal["new_build", "replicate", "improve", "repair"]
    seo_work_type: Literal[
        "website_build", "local_page", "blog", "website_audit", "gbp_update", "technical_seo", "general"
    ] = "website_build"
    repository_owner: str = Field(min_length=1, max_length=200)
    repository_name: str = Field(min_length=1, max_length=200)
    repository_url: str = Field(pattern=r"^https://github\.com/[^\s]+$", max_length=500)
    branch: str = Field(default="main", min_length=1, max_length=200)
    vercel_project_id: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=255)
    allowed_paths: list[str] = Field(min_length=1)
    prohibited_paths: list[str] = Field(default_factory=lambda: [".env*", "**/.env*", "node_modules/**", ".git/**"])
    publish_allowed: bool = False
    task_specific_instructions: Optional[str] = Field(default=None, max_length=2000)


class CodexWorkPacketRead(BaseModel):
    """A stored packet that can be copied into Codex without exposing secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_key: str
    client_id: str
    task_id: str
    status: str
    mode: str
    repository_owner: str
    repository_name: str
    repository_url: str
    branch: str
    vercel_project_id: str
    domain: str
    allowed_paths: list[str]
    prohibited_paths: list[str]
    publishing_allowed: bool
    packet_data: dict
    created_by: str
    created_at: datetime
    expires_at: datetime
    handed_off_by: Optional[str]
    handed_off_at: Optional[datetime]
    result_execution_id: Optional[str]
    quality: dict[str, Any] = Field(default_factory=dict)
    content_review: Optional["ContentReviewRead"] = None
    reused_existing: bool = False


class CodexHandoffCreate(BaseModel):
    """Record that a human copied this packet into an authorized Codex session."""

    model_config = ConfigDict(str_strip_whitespace=True)

    handed_off_by: str = Field(min_length=1, max_length=200)


class ConnectedCodexPacketCreate(BaseModel):
    """Prepare a packet from the client's already verified repository and website."""

    model_config = ConfigDict(str_strip_whitespace=True)

    operation_key: str = Field(min_length=1, max_length=120)
    created_by: str = Field(min_length=1, max_length=200)
    mode: Literal["new_build", "replicate", "improve", "repair"] = "improve"
    seo_work_type: Optional[Literal[
        "website_build", "local_page", "blog", "website_audit", "gbp_update", "technical_seo", "general"
    ]] = None
    publish_allowed: bool = False
    task_specific_instructions: Optional[str] = Field(default=None, max_length=2000)


class CodexHandoffRead(BaseModel):
    packet: CodexWorkPacketRead
    handoff_text: str


class ContentReviewCreate(BaseModel):
    """Owner review of local-page/blog output before independent verification."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reviewer: str = Field(min_length=1, max_length=200)
    status: Literal["approved", "rejected"]
    checklist: dict[str, bool]
    notes: str = Field(min_length=1, max_length=2000)


class ContentReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    task_id: str
    packet_id: str
    execution_id: str
    status: str
    reviewer: Optional[str]
    checklist: dict[str, bool]
    notes: str
    decided_at: Optional[datetime]
    created_at: datetime


class CodexResultTest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=300)
    status: Literal["passed", "failed", "not_run"]
    detail: Optional[str] = Field(default=None, max_length=1200)


class CodexHandoffResultCreate(BaseModel):
    """Structured evidence copied back from Codex; completion remains unverified."""

    model_config = ConfigDict(str_strip_whitespace=True)

    operation_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    outcome: Literal["completed", "blocked", "failed"]
    submitted_by: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=3000)
    changed_files: list[str] = Field(default_factory=list, max_length=200)
    tests: list[CodexResultTest] = Field(default_factory=list, max_length=100)
    commit_shas: list[str] = Field(default_factory=list, max_length=100)
    deployment_url: Optional[str] = Field(default=None, pattern=r"^https://[^\s]+$", max_length=1000)
    evidence: list[str] = Field(default_factory=list, max_length=100)
    verification_data: dict[str, Any] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list, max_length=50)
    actual_cost: float = Field(default=0.0, ge=0, le=10000)


class CodexHandoffResultRead(BaseModel):
    packet: CodexWorkPacketRead
    execution: SimulatedExecutionRead
    reused_existing: bool = False


class WebsiteGenerationTaskCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mode: Literal["new_build", "replicate", "improve"] = "replicate"
    requested_outcome: str = Field(min_length=1, max_length=1200)
    requested_by: str = Field(min_length=1, max_length=200)


class WebsiteMetricRead(BaseModel):
    """One saved aggregate-only website analytics snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    period_start: date
    period_end: date
    window_days: int
    unique_visitors: int
    pageviews: int
    call_clicks: int
    form_submits: int
    tracker_sites: list[str]
    source: str
    recorded_at: datetime


class WebsiteMetricSyncRequest(BaseModel):
    window_days: Literal[7, 30, 90] = 30


class WebsiteMetricSyncRead(BaseModel):
    snapshots: list[WebsiteMetricRead]
    unmatched_tracker_sites: list[str]
    reused_existing: bool


class WebsiteAnalyticsConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    tracker_sites: list[str]
    connection_status: str
    source: str
    last_checked_at: Optional[datetime]
    linked_at: datetime


class OnboardingAutomationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    intake_id: str
    status: str
    current_step: str
    steps: dict
    attempt_count: int
    max_attempts: int
    last_error: Optional[str]
    next_attempt_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ConnectionCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    client_id: str
    provider: str
    external_identifier: str
    display_name: str
    connection_data: dict
    match_evidence: dict
    match_kind: str
    status: str
    decided_by: Optional[str]
    decision_reason: Optional[str]
    decided_at: Optional[datetime]
    created_at: datetime


class ConnectionCandidateDecision(BaseModel):
    decision: Literal["approve", "reject"]
    decided_by: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=1000)


class OnboardingBackfillRead(BaseModel):
    queued_client_ids: list[str]
    reused_client_ids: list[str]


class ScheduledJobCreate(BaseModel):
    job_key: str = Field(min_length=1, max_length=160)
    job_type: Literal[
        "health_check",
        "website_metrics_sync",
        "search_console_sync",
        "daily_client_plan",
        "onboarding_automation",
    ]
    client_id: Optional[str] = None
    interval_minutes: int = Field(default=1440, ge=1, le=525600)
    parameters: dict[str, Any] = Field(default_factory=dict)
    next_run_at: Optional[datetime] = None


class ScheduledJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_key: str
    job_type: str
    client_id: Optional[str]
    interval_minutes: int
    parameters: dict[str, Any]
    next_run_at: datetime
    last_run_at: Optional[datetime]
    last_started_at: Optional[datetime]
    last_status: str
    last_error: Optional[str]
    consecutive_failures: int
    last_duration_seconds: Optional[float]
    enabled: bool


class ScheduledJobRunRead(BaseModel):
    job_id: str
    job_key: str
    status: str
    error: Optional[str] = None


class DailyPlanGenerateRequest(BaseModel):
    """Choose how much live evidence to collect for today's client plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    depth: Literal["simple", "in_depth"] = "simple"
    focus: Literal["all", "seo", "fulfillment", "reporting"] = "all"
    created_by: str = Field(default="Agency Owner", min_length=1, max_length=200)
    create_tasks: bool = False


class DailyClientPlanRead(BaseModel):
    """One persisted, deduplicated client plan for a calendar day."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: str
    plan_date: date
    depth: str
    focus: str
    items: list[dict[str, Any]]
    source_summary: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


class DailyPlanTaskCreate(BaseModel):
    """Convert one plan recommendation into a normal approval-required task."""

    model_config = ConfigDict(str_strip_whitespace=True)

    created_by: str = Field(default="Agency Owner", min_length=1, max_length=200)
