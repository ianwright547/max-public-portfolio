"""Build and track safe, repeatable Codex fulfillment handoffs."""

from datetime import datetime, timedelta
from fnmatch import fnmatch
import json
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.notification_service import notify_execution_result
from app.website_execution import SECRET_PATTERNS


class WorkPacketError(Exception):
    """An expected packet safety failure that routes can return clearly."""

    def __init__(self, detail: str, status_code: int = 409) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


LOCAL_SEO_ROUTING = {
    "website_build": {
        "files": [
            "docs/knowledge/skills/local-seo/SKILL.md",
            "docs/knowledge/sops/local-seo/00-local-seo-roadmap.md",
            "docs/knowledge/sops/local-seo/03-local-pages-and-content.md",
            "docs/knowledge/sops/local-seo/05-technical-local-seo.md",
            "docs/knowledge/checklists/local-seo/local-seo-publication-checklist.md",
        ],
        "guidance": "Build in the measured roadmap order. A website supports local visibility; do not promise rankings or treat a single metric as a universal rank.",
    },
    "local_page": {
        "files": [
            "docs/knowledge/skills/local-seo/SKILL.md",
            "docs/knowledge/skills/local-content-brief/SKILL.md",
            "docs/knowledge/sops/local-seo/01-local-seo-research-and-strategy.md",
            "docs/knowledge/sops/local-seo/03-local-pages-and-content.md",
            "docs/knowledge/checklists/local-seo/local-seo-publication-checklist.md",
        ],
        "guidance": "Map one real service or location intent to each page. Do not create city-swapped doorway pages or imply a physical office that does not exist.",
    },
    "blog": {
        "files": [
            "docs/knowledge/skills/local-seo/SKILL.md",
            "docs/knowledge/skills/local-content-brief/SKILL.md",
            "docs/knowledge/sops/06-blog-and-content-production.md",
            "docs/knowledge/sops/universal_human_writing_sop.md",
            "docs/knowledge/checklists/local-seo/local-seo-publication-checklist.md",
        ],
        "guidance": "Write for a documented customer need, use only supported local facts, and run the Human Writing SOP before publication.",
    },
    "website_audit": {
        "files": [
            "docs/knowledge/skills/local-seo/SKILL.md",
            "docs/knowledge/skills/local-website-audit/SKILL.md",
            "docs/knowledge/sops/local-seo/07-local-website-audit.md",
            "docs/knowledge/checklists/local-seo/local-seo-audit-checklist.md",
        ],
        "guidance": "Separate measured observations from hypotheses. An audit recommends work; it does not publish changes.",
    },
    "gbp_update": {
        "files": [
            "docs/knowledge/skills/local-seo/SKILL.md",
            "docs/knowledge/sops/local-seo/02-google-business-profile.md",
            "docs/knowledge/checklists/local-seo/local-seo-publication-checklist.md",
        ],
        "guidance": "Google Business Profile changes require recorded approval. Use real services, hours, and business facts only.",
    },
    "technical_seo": {
        "files": [
            "docs/knowledge/skills/local-seo/SKILL.md",
            "docs/knowledge/sops/local-seo/05-technical-local-seo.md",
            "docs/knowledge/checklists/local-seo/local-seo-publication-checklist.md",
        ],
        "guidance": "Inspect the existing implementation first and keep changes scoped. Verify canonical, indexability, status-code, sitemap, and schema effects where relevant.",
    },
    "general": {
        "files": [],
        "guidance": "Use the task outcome and approved facts as the complete scope. Do not extend work into unrelated SEO changes.",
    },
}

# These contracts make a handoff actionable and make a returned "completed"
# claim auditable.  They intentionally describe evidence, not implementation
# details, so Codex can work in any supported repository stack.
SPECIALIZED_ACCEPTANCE_CONTRACTS = {
    "technical_seo": {
        "name": "Technical SEO fix",
        "required_checks": [
            "indexability and robots directives",
            "canonical URLs and redirect/status-code behavior",
            "sitemap and structured-data effects when relevant",
            "relevant build, lint, type, and test checks",
        ],
        "result_keys": ["technical_checks"],
        "guidance": "Return technical_checks as an object keyed by check name. Each value must state observed result and evidence (URL, command output, or file). Mark failed checks explicitly; do not imply a fix from an unverified hypothesis.",
    },
    "local_page": {
        "name": "Local service/location page",
        "required_checks": [
            "target page path and live URL",
            "one service/location search intent with a unique H1, title, and meta description",
            "approved business facts and service-area source used",
            "internal links, CTA/contact path, accessibility, and schema when relevant",
            "no doorway, city-swapped, or unsupported location claims",
        ],
        "result_keys": ["page_url_or_path", "facts_source", "content_scope_confirmed"],
        "guidance": "Return the exact page_url_or_path and facts_source. Set content_scope_confirmed true only after confirming the page represents a real service/location supported by the approved facts. Never create a thin city-swapped doorway page.",
    },
    "gbp_update": {
        "name": "Google Business Profile work",
        "required_checks": [
            "connected GBP location identifier and business name",
            "approved business facts, offer/service, and call-to-action URL",
            "draft/approval/publish state",
            "provider response ID and timestamp when published",
        ],
        "result_keys": ["business_facts_confirmed", "approval_state"],
        "guidance": "Return a draft or publish evidence only for the connected location. Set business_facts_confirmed true after checking approved facts. Publishing is never implied by a draft; if approval_state is published, include provider_post_id and publish evidence.",
    },
}

DEFAULT_ALLOWED_PATHS = [
    "app/**",
    "src/**",
    "pages/**",
    "components/**",
    "public/**",
    "styles/**",
    "content/**",
    "docs/**",
    "package.json",
    "next.config.*",
    "vite.config.*",
]


def packet_quality(packet: models.CodexWorkPacket) -> dict:
    """Evaluate whether a packet is safe and complete enough to hand off."""
    data = packet.packet_data or {}
    checks: list[dict] = []

    def check(key: str, passed: bool, detail: str, remediation: str) -> None:
        checks.append(
            {
                "key": key,
                "status": "passed" if passed else "blocked",
                "detail": detail,
                "remediation": "" if passed else remediation,
            }
        )

    check(
        "packet_not_expired",
        packet.expires_at > datetime.utcnow(),
        "Packet expiry is still in the future.",
        "Generate a fresh packet before handoff.",
    )
    check(
        "client_identity",
        bool(data.get("client_identity", {}).get("client_id") == packet.client_id and data.get("client_identity", {}).get("business_name")),
        "Packet identity matches the saved client.",
        "Regenerate the packet from the correct client task.",
    )
    check(
        "evidence_source",
        bool(data.get("source_labels", {}).get("finding_id") and data.get("source_labels", {}).get("finding_evidence")),
        "The packet retains the evidence-backed finding source.",
        "Attach an open, evidence-backed finding before creating the packet.",
    )
    contract = data.get("measurement_contract") or {}
    check(
        "measurement_contract",
        all(str(contract.get(key, "")).strip() for key in ("expected_result", "success_metric", "verification_window")),
        "Expected result, success metric, and verification window are present.",
        "Complete the task acceptance fields and regenerate the packet.",
    )
    criteria = data.get("acceptance_criteria")
    check(
        "acceptance_criteria",
        isinstance(criteria, list) and bool(criteria) and all(str(item).strip() for item in criteria),
        "The packet has explicit acceptance criteria.",
        "Add at least one concrete acceptance criterion.",
    )
    check(
        "file_scope",
        isinstance(packet.allowed_paths, list) and bool(packet.allowed_paths) and isinstance(packet.prohibited_paths, list),
        "Allowed and prohibited file scopes are defined.",
        "Regenerate the packet with an explicit file scope.",
    )
    work_type = data.get("local_seo_work_type", "general")
    specialized = data.get("specialized_acceptance_contract")
    if work_type in SPECIALIZED_ACCEPTANCE_CONTRACTS:
        check(
            "specialized_contract",
            isinstance(specialized, dict) and bool(specialized.get("result_keys")) and bool(specialized.get("required_checks")),
            f"The `{work_type}` acceptance contract is attached.",
            "Regenerate the packet so the specialized acceptance contract is included.",
        )
    if work_type in {"local_page", "blog"}:
        brief = data.get("content_brief")
        check(
            "content_brief",
            isinstance(brief, dict) and bool(brief.get("outline")) and bool(brief.get("page_requirements")),
            "The content brief contains a bounded outline and requirements.",
            "Regenerate the content packet with the approved-facts brief attached.",
        )
    blocked = [item for item in checks if item["status"] == "blocked"]
    return {
        "status": "blocked" if blocked else "ready",
        "checks": checks,
        "summary": {
            "passed": len(checks) - len(blocked),
            "blocked": len(blocked),
            "total": len(checks),
        },
    }


def normalized_domain(value: str) -> str:
    """Compare domains consistently while refusing an empty hostname."""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise WorkPacketError("A valid production domain is required", 422)
    return host


def _approved_facts(database: Session, client_id: str) -> dict:
    profile = database.scalar(
        select(models.OfficialProfile).where(models.OfficialProfile.client_id == client_id)
    )
    if profile is None:
        return {"source": "client_record", "facts": {}}
    return {"source": "official_profile", "facts": profile.profile_data}


def _content_brief(
    database: Session,
    *,
    task: models.Task,
    client: models.Client,
    facts: dict,
    seo_work_type: str,
) -> Optional[dict]:
    """Build a bounded content brief from approved facts and saved opportunities."""
    if seo_work_type not in {"local_page", "blog"}:
        return None
    finding = database.get(models.Finding, task.source_finding_id)
    search_console = database.scalar(
        select(models.SearchConsoleConnection).where(
            models.SearchConsoleConnection.client_id == client.id,
            models.SearchConsoleConnection.connection_status.in_({"linked", "connected"}),
        )
    )
    query_opportunities = []
    if search_console is not None:
        for row in (search_console.last_query_rows or [])[:10]:
            if not isinstance(row, dict) or not str(row.get("key", "")).strip():
                continue
            query_opportunities.append(
                {
                    "query": str(row["key"])[:200],
                    "impressions": row.get("impressions", 0),
                    "clicks": row.get("clicks", 0),
                    "position": row.get("position"),
                }
            )
    if seo_work_type == "local_page":
        outline = [
            "Answer the one real service or location intent named by the task.",
            "Explain the approved service, proof, process, and customer fit without unsupported claims.",
            "Add an intent-matched FAQ or helpful next-step section only when supported by client facts.",
            "End with an approved phone, form, booking, or contact CTA.",
        ]
        page_requirements = [
            "one unique title, meta description, and H1",
            "clear internal links to relevant service/contact pages",
            "mobile-readable layout and accessible headings/links",
            "accurate LocalBusiness/service schema only when facts support it",
        ]
    else:
        outline = [
            "Answer the documented customer question or need in the task.",
            "Use the client's approved expertise, services, and service area only where supported.",
            "Provide practical steps, limitations, and a relevant next action.",
            "Link to the most relevant approved service or contact page.",
        ]
        page_requirements = [
            "one descriptive title, meta description, and H1",
            "clear author/business-fact sourcing and no invented claims",
            "useful internal links and a measurable CTA when appropriate",
            "run the Human Writing SOP before publication",
        ]
    return {
        "content_type": seo_work_type,
        "working_title_or_topic": task.requested_outcome[:300],
        "intent_source": {
            "finding_id": finding.id if finding is not None else None,
            "finding_source": finding.source if finding is not None else None,
            "task_outcome": task.requested_outcome,
        },
        "approved_facts_source": facts["source"],
        "approved_fact_fields": sorted(str(key) for key in (facts.get("facts") or {}).keys())[:80],
        "search_console_source": (
            {
                "property_url": search_console.property_url,
                "last_sync_start": search_console.last_query_start_date.isoformat() if search_console.last_query_start_date else None,
                "last_sync_end": search_console.last_query_end_date.isoformat() if search_console.last_query_end_date else None,
            }
            if search_console is not None
            else None
        ),
        "query_opportunities": query_opportunities,
        "outline": outline,
        "page_requirements": page_requirements,
        "prohibited_claims": [
            "Do not invent services, locations, reviews, credentials, awards, guarantees, or results.",
            "Do not create thin city-swapped doorway pages or imply a physical office that is not supported.",
        ],
        "acceptance_checks_to_return": [
            "Intent and content scope match the approved task and finding evidence.",
            "Every material business fact is traceable to the approved facts source.",
            "The published draft passes the listed title, H1, CTA, accessibility, and link checks.",
        ],
    }


def _packet_data(
    database: Session,
    task: models.Task,
    client: models.Client,
    request: schemas.CodexWorkPacketCreate,
    connection: models.WebsiteConnection,
) -> dict:
    finding = database.get(models.Finding, task.source_finding_id)
    if finding is None or finding.client_id != client.id or not finding.evidence:
        raise WorkPacketError("Task must remain linked to an evidence-backed finding")

    decisions = list(
        database.scalars(
            select(models.TaskDecision).where(
                models.TaskDecision.task_id == task.id,
                models.TaskDecision.client_id == client.id,
                models.TaskDecision.decision == "approved",
            )
        )
    )
    if not decisions:
        raise WorkPacketError("An approved task decision is required before creating a work packet")

    facts = _approved_facts(database, client.id)
    content_brief = _content_brief(
        database,
        task=task,
        client=client,
        facts=facts,
        seo_work_type=request.seo_work_type,
    )
    gbp_connection = database.scalar(
        select(models.GoogleBusinessProfileConnection).where(
            models.GoogleBusinessProfileConnection.client_id == client.id,
            models.GoogleBusinessProfileConnection.connection_status.in_({"linked", "connected"}),
        )
    )
    if request.seo_work_type == "gbp_update" and gbp_connection is None:
        raise WorkPacketError("A connected Google Business Profile location is required for GBP work")
    return {
        "packet_version": "1.0",
        "task_summary": task.title,
        "exact_requested_outcome": task.requested_outcome,
        "client_identity": {
            "client_id": client.id,
            "business_name": client.business_name,
            "service_start_date": client.service_start_date.isoformat(),
        },
        "approved_client_facts": facts,
        "source_labels": {
            "finding_id": finding.id,
            "finding_source": finding.source,
            "finding_evidence": finding.evidence,
        },
        "github": {
            "owner": request.repository_owner,
            "repository": request.repository_name,
            "url": request.repository_url,
            "branch": request.branch,
        },
        "vercel": {
            "project_id": connection.external_project_id,
            "production_domain": normalized_domain(connection.production_url),
        },
        "google_business_profile": (
            {
                "account_id": gbp_connection.account_id,
                "location_id": gbp_connection.location_id,
                "location_name": gbp_connection.location_name,
                "connection_status": gbp_connection.connection_status,
            }
            if gbp_connection is not None and request.seo_work_type == "gbp_update"
            else None
        ),
        "mode": request.mode,
        "skills_and_sops": [
            "docs/knowledge/sops/05-codex-work-packet.md",
            "docs/knowledge/sops/07-website-generation.md",
            *LOCAL_SEO_ROUTING[request.seo_work_type]["files"],
        ],
        "local_seo_work_type": request.seo_work_type,
        "local_seo_guidance": LOCAL_SEO_ROUTING[request.seo_work_type]["guidance"],
        "specialized_acceptance_contract": SPECIALIZED_ACCEPTANCE_CONTRACTS.get(request.seo_work_type),
        "content_brief": content_brief,
        "allowed_paths": request.allowed_paths,
        "prohibited_paths": request.prohibited_paths,
        "seo_requirements": [
            "Use only verified client facts; do not invent services, locations, results, reviews, or credentials.",
            "Preserve or create correct H1/H2 structure, title tags, meta descriptions, internal links, alt text, local business information, structured data, sitemap behavior, mobile usability, and accessibility when the task requires them.",
        ],
        "design_requirements": [
            "For replicate work, preserve the Demo Reference Client approved design system: type scale, layout, spacing, header, footer, navigation, buttons, cards, responsive behavior, and visual rhythm.",
            "Change client content, brand colors, approved assets, services, service areas, and calls to action only where this task requires it.",
            "Do not redesign unrelated components.",
        ],
        "acceptance_criteria": [
            task.requested_outcome,
            "Only allowed files are changed.",
            "The resulting site remains associated with this packet's client, repository, Vercel project, and domain.",
        ],
        "measurement_contract": {
            "expected_result": task.expected_result,
            "success_metric": task.success_metric,
            "verification_window": task.verification_window,
        },
        "tests_and_checks": [
            "Inspect the repository before editing.",
            "Run the repository's relevant tests, build, lint, and type checks when available.",
            "Verify expected files exist and report every changed file.",
            "Stop and report a mismatch, missing expected files, or unexpected client identity.",
        ],
        "cost_guidance": "Prefer the smallest correct change. Stop after two failed major attempts or three failed small attempts and report the blocker.",
        "approval_and_publishing_state": {
            "task_status": task.status,
            "approved_decision_ids": [decision.id for decision in decisions],
            "publish_allowed": request.publish_allowed,
            "authorization": "Task approval authorizes this scoped work only; this packet does not authorize unrelated changes.",
        },
        "required_final_response_format": [
            "summary of completed work",
            "changed files",
            "tests and checks run with results",
            "deployment and domain verification result",
            "evidence and any blockers or assumptions",
            "structured verification_data matching the work-type acceptance contract",
            "verification_data.acceptance_checks with one passed, evidence-backed entry for every packet acceptance criterion",
        ],
        "safety_instruction": "Use only this client's approved information, repository, domain, assets, and Vercel project. Do not use another client's files, facts, domain, repository, or deployment project. Never include or request credentials in this packet.",
        "task_specific_instructions": request.task_specific_instructions,
    }


def create_work_packet(
    database: Session, task_id: str, request: schemas.CodexWorkPacketCreate
) -> tuple[models.CodexWorkPacket, bool]:
    """Create or safely reuse a packet for one approved client task."""
    existing = database.scalar(
        select(models.CodexWorkPacket).where(models.CodexWorkPacket.operation_key == request.operation_key)
    )
    if existing is not None:
        if existing.task_id != task_id:
            raise WorkPacketError("This operation key already belongs to a different task")
        return existing, True

    task = database.get(models.Task, task_id)
    if task is None:
        raise WorkPacketError("Task not found", 404)
    if task.status not in {"approved", "ready"}:
        raise WorkPacketError("Only an approved or ready task can receive a Codex work packet")
    if request.publish_allowed and task.status != "ready":
        raise WorkPacketError("Publishing requires a ready task after all dependencies are verified")
    client = database.get(models.Client, task.client_id)
    if client is None:
        raise WorkPacketError("Task client not found", 404)
    connection = database.scalar(
        select(models.WebsiteConnection).where(models.WebsiteConnection.client_id == client.id)
    )
    if connection is None:
        raise WorkPacketError("A verified website connection is required before creating a Codex work packet")
    if connection.external_project_id != request.vercel_project_id:
        raise WorkPacketError("Vercel project does not match this client")
    if normalized_domain(connection.production_url) != normalized_domain(request.domain):
        raise WorkPacketError("Production domain does not match this client")
    repository = database.scalar(
        select(models.GitHubRepositoryConnection).where(
            models.GitHubRepositoryConnection.client_id == client.id
        )
    )
    if repository is None:
        raise WorkPacketError("A verified GitHub repository connection is required before creating a Codex work packet")
    if (
        repository.owner != request.repository_owner
        or repository.repository_name != request.repository_name
        or repository.repository_url != request.repository_url
        or repository.default_branch != request.branch
    ):
        raise WorkPacketError("GitHub repository or branch does not match this client")

    packet_data = _packet_data(database, task, client, request, connection)
    packet = models.CodexWorkPacket(
        operation_key=request.operation_key,
        client_id=client.id,
        task_id=task.id,
        mode=request.mode,
        repository_owner=request.repository_owner,
        repository_name=request.repository_name,
        repository_url=request.repository_url,
        branch=request.branch,
        vercel_project_id=connection.external_project_id,
        domain=normalized_domain(request.domain),
        allowed_paths=request.allowed_paths,
        prohibited_paths=request.prohibited_paths,
        publishing_allowed=request.publish_allowed,
        packet_data=packet_data,
        created_by=request.created_by,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    database.add(packet)
    database.commit()
    database.refresh(packet)
    return packet, False


def infer_seo_work_type(task: models.Task) -> str:
    text = f"{task.title} {task.requested_outcome} {task.reason}".casefold()
    if any(term in text for term in ("audit", "inspect", "crawl")):
        return "website_audit"
    if any(term in text for term in ("blog", "article")):
        return "blog"
    if any(term in text for term in ("location page", "service page", "landing page")):
        return "local_page"
    if any(term in text for term in ("sitemap", "canonical", "schema", "redirect", "technical seo", "index")):
        return "technical_seo"
    if any(term in text for term in ("google business", "gbp")):
        return "gbp_update"
    if any(term in text for term in ("website", "site", "page", "seo")):
        return "website_build"
    return "general"


def prepare_connected_work_packet(
    database: Session,
    task_id: str,
    request: schemas.ConnectedCodexPacketCreate,
) -> tuple[models.CodexWorkPacket, bool]:
    """Prepare a packet without making the owner re-enter verified connection IDs."""
    task = database.get(models.Task, task_id)
    if task is None:
        raise WorkPacketError("Task not found", 404)
    repository = database.scalar(
        select(models.GitHubRepositoryConnection).where(
            models.GitHubRepositoryConnection.client_id == task.client_id,
            models.GitHubRepositoryConnection.connection_status.in_({"linked", "connected"}),
        )
    )
    website = database.scalar(
        select(models.WebsiteConnection).where(
            models.WebsiteConnection.client_id == task.client_id,
            models.WebsiteConnection.connection_status.in_({"linked", "connected"}),
        )
    )
    if repository is None:
        raise WorkPacketError("A connected, verified GitHub repository is required")
    if website is None:
        raise WorkPacketError("A connected, verified website/Vercel project is required")
    return create_work_packet(
        database,
        task_id,
        schemas.CodexWorkPacketCreate(
            operation_key=request.operation_key,
            created_by=request.created_by,
            mode=request.mode,
            seo_work_type=request.seo_work_type or infer_seo_work_type(task),
            repository_owner=repository.owner,
            repository_name=repository.repository_name,
            repository_url=repository.repository_url,
            branch=repository.default_branch,
            vercel_project_id=website.external_project_id,
            domain=website.production_url,
            allowed_paths=DEFAULT_ALLOWED_PATHS,
            publish_allowed=request.publish_allowed,
            task_specific_instructions=request.task_specific_instructions,
        ),
    )


def render_handoff_text(packet: models.CodexWorkPacket) -> str:
    """Render the persisted packet as one complete, copyable Codex prompt."""
    data = packet.packet_data
    lines = [
        "# Max Codex Fulfillment Handoff",
        "",
        f"Packet: `{packet.id}`",
        f"Client: `{packet.client_id}` — {data['client_identity']['business_name']}",
        f"Task: `{packet.task_id}`",
        f"Mode: `{packet.mode}`",
        f"Publishing authorized: `{'yes' if packet.publishing_allowed else 'no'}`",
        "",
        "## Requested outcome",
        data["exact_requested_outcome"],
        "",
        "## Repository and production target",
        f"- Repository: {packet.repository_url}",
        f"- Branch: `{packet.branch}`",
        f"- Vercel project: `{packet.vercel_project_id}`",
        f"- Production domain: `{packet.domain}`",
        *(
            [
                f"- GBP location: `{data['google_business_profile']['location_id']}`",
                f"- GBP location name: `{data['google_business_profile']['location_name']}`",
            ]
            if data.get("google_business_profile")
            else []
        ),
        "",
        "## Client facts and source evidence",
        "```json",
        json.dumps(
            {
                "approved_client_facts": data["approved_client_facts"],
                "source_labels": data["source_labels"],
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        "```",
        "",
        "## Required instructions",
        data["safety_instruction"],
        data["local_seo_guidance"],
        *[f"- {item}" for item in data["seo_requirements"]],
        *[f"- {item}" for item in data["design_requirements"]],
        "",
        "## Scope",
        "Allowed paths:",
        *[f"- `{item}`" for item in packet.allowed_paths],
        "Prohibited paths:",
        *[f"- `{item}`" for item in packet.prohibited_paths],
        "",
        "## Acceptance criteria",
        *[f"- {item}" for item in data["acceptance_criteria"]],
        "",
        "## Measurement contract",
        f"- Expected result: {data['measurement_contract']['expected_result']}",
        f"- Success metric: {data['measurement_contract']['success_metric']}",
        f"- Verification window: {data['measurement_contract']['verification_window']}",
        "",
        "## Tests and stopping rules",
        *[f"- {item}" for item in data["tests_and_checks"]],
        f"- {data['cost_guidance']}",
        "",
        "## Read these repository knowledge files before working",
        *[f"- `{item}`" for item in data["skills_and_sops"]],
        "",
        "## Required final response",
        *[f"- {item}" for item in data["required_final_response_format"]],
        "- Explicitly state `completed`, `blocked`, or `failed`.",
        "- Do not claim deployment or verification without evidence.",
    ]
    contract = data.get("specialized_acceptance_contract")
    if contract:
        lines.extend([
            "",
            f"## Specialized acceptance contract: {contract['name']}",
            *[f"- Required check: {item}" for item in contract["required_checks"]],
            f"- {contract['guidance']}",
            "- Return these verification_data keys: " + ", ".join(contract["result_keys"]),
        ])
    if data.get("content_brief"):
        brief = data["content_brief"]
        lines.extend([
            "",
            "## Evidence-backed content brief",
            f"- Content type: `{brief['content_type']}`",
            f"- Working title/topic: {brief['working_title_or_topic']}",
            f"- Approved facts source: `{brief['approved_facts_source']}`",
            *[f"- Outline: {item}" for item in brief["outline"]],
            *[f"- Requirement: {item}" for item in brief["page_requirements"]],
            *[f"- Prohibited claim: {item}" for item in brief["prohibited_claims"]],
            "- Return acceptance_checks for each content-brief acceptance check with supporting evidence.",
        ])
    if data.get("task_specific_instructions"):
        lines.extend(["", "## Task-specific instructions", data["task_specific_instructions"]])
    return "\n".join(lines)


def _dependencies_verified(database: Session, task: models.Task) -> None:
    dependency_ids = list(
        database.scalars(
            select(models.TaskDependency.depends_on_task_id).where(
                models.TaskDependency.task_id == task.id
            )
        )
    )
    unverified = [
        dependency_id
        for dependency_id in dependency_ids
        if (database.get(models.Task, dependency_id) is None or database.get(models.Task, dependency_id).status != "verified")
    ]
    if unverified:
        raise WorkPacketError(f"Dependencies must be verified first: {', '.join(unverified)}")


def mark_packet_handed_off(
    database: Session,
    packet: models.CodexWorkPacket,
    *,
    handed_off_by: str,
) -> models.CodexWorkPacket:
    if packet.status == "handed_off":
        return packet
    if packet.status != "generated":
        raise WorkPacketError(f"Packet cannot be handed off from status {packet.status}")
    if packet.expires_at <= datetime.utcnow():
        raise WorkPacketError("The Codex work packet has expired; generate a fresh packet")
    quality = packet_quality(packet)
    if quality["status"] != "ready":
        blocked = ", ".join(item["key"] for item in quality["checks"] if item["status"] == "blocked")
        raise WorkPacketError(f"Packet quality gate blocked handoff: {blocked}. Review the packet quality checks and regenerate if needed")
    task = database.get(models.Task, packet.task_id)
    if task is None or task.client_id != packet.client_id:
        raise WorkPacketError("Packet task is missing or has a client mismatch")
    if task.status not in {"approved", "ready"}:
        raise WorkPacketError(f"Codex handoff requires an approved or ready task; task is {task.status}")
    _dependencies_verified(database, task)
    if task.status == "approved":
        database.add(models.TaskStatusEvent(
            client_id=task.client_id,
            task_id=task.id,
            from_status="approved",
            to_status="ready",
            changed_by=handed_off_by,
            reason="Dependencies checked for Codex handoff",
        ))
        task.status = "ready"
    database.add(models.TaskStatusEvent(
        client_id=task.client_id,
        task_id=task.id,
        from_status="ready",
        to_status="running",
        changed_by=handed_off_by,
        reason=f"Codex packet {packet.id} handed off",
    ))
    task.status = "running"
    packet.status = "handed_off"
    packet.handed_off_by = handed_off_by
    packet.handed_off_at = datetime.utcnow()
    database.flush()
    return packet


def _validate_result(packet: models.CodexWorkPacket, request: schemas.CodexHandoffResultCreate) -> None:
    serialized = json.dumps(request.model_dump(), default=str)
    if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
        raise WorkPacketError("The Codex result appears to contain a credential or secret", 422)
    if request.outcome == "blocked" and not request.blockers:
        raise WorkPacketError("A blocked Codex result requires at least one blocker", 422)
    if request.outcome == "completed" and any(test.status == "failed" for test in request.tests):
        raise WorkPacketError("A result with failed tests cannot be recorded as completed", 422)
    contract = packet.packet_data.get("specialized_acceptance_contract")
    if request.outcome == "completed" and contract:
        missing = [
            key for key in contract.get("result_keys", [])
            if key not in request.verification_data
            or request.verification_data[key] in (None, "", [], {})
        ]
        if missing:
            raise WorkPacketError(
                "Completed result is missing specialized verification_data: " + ", ".join(missing),
                422,
            )
        work_type = packet.packet_data.get("local_seo_work_type")
        if work_type == "technical_seo":
            checks = request.verification_data.get("technical_checks")
            if not isinstance(checks, (dict, list)) or not checks:
                raise WorkPacketError("technical_checks must contain at least one recorded check", 422)
            failed = []
            values = checks.values() if isinstance(checks, dict) else checks
            for value in values:
                if isinstance(value, dict) and str(value.get("status", "")).casefold() in {"failed", "blocked"}:
                    failed.append(value)
            if failed:
                raise WorkPacketError("technical_checks contains failed or blocked checks", 422)
        elif work_type == "local_page" and request.verification_data.get("content_scope_confirmed") is not True:
            raise WorkPacketError("content_scope_confirmed must be true for a completed local page", 422)
        elif work_type == "gbp_update":
            state = str(request.verification_data.get("approval_state", "")).casefold()
            if state not in {"draft", "approved", "published", "blocked"}:
                raise WorkPacketError("GBP approval_state must be draft, approved, published, or blocked", 422)
            if state == "published" and not request.verification_data.get("provider_post_id"):
                raise WorkPacketError("Published GBP work requires provider_post_id", 422)
    seen: set[str] = set()
    for path in request.changed_files:
        if not path or path.startswith("/") or ".." in path.split("/") or path in seen:
            raise WorkPacketError("A returned changed-file path is invalid", 422)
        if any(fnmatch(path, pattern) for pattern in packet.prohibited_paths):
            raise WorkPacketError(f"Returned file is prohibited by the packet: {path}", 422)
        if not any(fnmatch(path, pattern) for pattern in packet.allowed_paths):
            raise WorkPacketError(f"Returned file is outside the packet scope: {path}", 422)
        seen.add(path)
    if request.outcome == "completed" and not request.evidence:
        raise WorkPacketError("A completed Codex result requires at least one evidence item", 422)
    if request.outcome == "completed":
        acceptance_checks = request.verification_data.get("acceptance_checks")
        criteria = packet.packet_data.get("acceptance_criteria") or []
        if not isinstance(acceptance_checks, list) or len(acceptance_checks) < len(criteria):
            raise WorkPacketError(
                "Completed result requires one acceptance_checks entry for every packet criterion",
                422,
            )
        seen_criteria: set[str] = set()
        for check in acceptance_checks:
            if not isinstance(check, dict) or not str(check.get("criterion", "")).strip():
                raise WorkPacketError("Each acceptance_checks entry requires a criterion", 422)
            criterion_key = " ".join(str(check["criterion"]).casefold().split())
            if criterion_key in seen_criteria:
                raise WorkPacketError("Completed result acceptance_checks cannot repeat a criterion", 422)
            seen_criteria.add(criterion_key)
            if str(check.get("status", "")).casefold() != "passed":
                raise WorkPacketError("Completed result acceptance_checks must all be passed", 422)
            evidence = check.get("evidence")
            if not evidence or (isinstance(evidence, list) and not any(str(value).strip() for value in evidence)):
                raise WorkPacketError("Each passed acceptance check requires evidence", 422)


def record_codex_result(
    database: Session,
    packet: models.CodexWorkPacket,
    request: schemas.CodexHandoffResultCreate,
) -> tuple[models.FulfillmentExecution, bool]:
    existing = database.scalar(
        select(models.FulfillmentExecution).where(
            models.FulfillmentExecution.operation_key == request.operation_key
        )
    )
    if existing is not None:
        if existing.task_id != packet.task_id or packet.result_execution_id not in {None, existing.id}:
            raise WorkPacketError("This result operation key belongs to another task or packet")
        return existing, True
    if packet.status != "handed_off":
        raise WorkPacketError("Record the Codex handoff before submitting its result")
    if packet.result_execution_id is not None:
        raise WorkPacketError("This Codex packet already has a result")
    task = database.get(models.Task, packet.task_id)
    if task is None or task.client_id != packet.client_id or task.status != "running":
        raise WorkPacketError("The packet task is not in the expected running state")
    _validate_result(packet, request)
    now = datetime.utcnow()
    error_message = None
    if request.outcome in {"blocked", "failed"}:
        error_message = "; ".join(request.blockers)[:1000] or request.summary[:1000]
    execution = models.FulfillmentExecution(
        operation_key=request.operation_key,
        client_id=packet.client_id,
        task_id=packet.task_id,
        status=request.outcome,
        intended_actions=[task.requested_outcome, "Complete the scoped Codex handoff", "Return evidence for independent verification"],
        simulated_changed_files=request.changed_files,
        simulated_test_results=[{**item.model_dump(), "simulated": False} for item in request.tests],
        evidence={
            "executor": "codex_handoff",
            "simulated": False,
            "packet_id": packet.id,
            "task_id": packet.task_id,
            "client_id": packet.client_id,
            "summary": request.summary,
            "commit_shas": request.commit_shas,
            "deployment_url": request.deployment_url,
            "output_url": request.deployment_url,
            "evidence": request.evidence,
            "verification_data": request.verification_data,
            "blockers": request.blockers,
            "submitted_by": request.submitted_by,
            "verification_required": request.outcome == "completed",
        },
        estimated_cost=request.actual_cost,
        attempt_count=1,
        retry_delays_seconds=[],
        failure_type="external_blocker" if request.outcome == "blocked" else "external_failure" if request.outcome == "failed" else None,
        error_message=error_message,
        started_at=packet.handed_off_at or now,
        completed_at=now,
    )
    database.add(execution)
    database.flush()
    database.add(models.TaskStatusEvent(
        client_id=task.client_id,
        task_id=task.id,
        from_status="running",
        to_status=request.outcome,
        changed_by=request.submitted_by,
        reason=("Codex returned completed work; verification remains separate" if request.outcome == "completed" else error_message),
    ))
    task.status = request.outcome
    packet.status = request.outcome
    packet.result_execution_id = execution.id
    notify_execution_result(database, execution, task)
    database.flush()
    return execution, False
