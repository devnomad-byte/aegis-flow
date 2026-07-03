from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
)
from backend.app.audit.schemas import AuditEventCreate, AuditEventRead
from backend.app.audit.store import AuditEventFilters, AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from fastapi.testclient import TestClient


class PermissionAwareProjectProvider(ProjectAccessProvider):
    def __init__(self, projects: Iterable[ProjectSummary]) -> None:
        self._projects = {project.id: project for project in projects}

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return list(self._projects.values())

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        if required_permission not in project.permissions:
            raise PermissionError(required_permission)
        return project


class InMemoryAuditEventStore(AuditEventStore):
    def __init__(self, events: list[AuditEventRead] | None = None) -> None:
        self.events = events or []
        self.recorded: list[AuditEventCreate] = []
        self.project_filters: list[AuditEventFilters] = []
        self.global_filters: list[AuditEventFilters] = []

    async def record_project_event(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: str,
        result: str = "success",
        risk_level: str = "low",
        metadata: dict[str, object] | None = None,
    ) -> None:
        created = AuditEventCreate(
            project_id=project_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            risk_level=risk_level,
            metadata=metadata or {},
        )
        self.recorded.append(created)
        self.events.append(
            AuditEventRead(
                id=uuid4(),
                created_at=datetime.now(UTC),
                **created.model_dump(),
            )
        )

    async def record_global_event(
        self,
        *,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: str,
        result: str = "success",
        risk_level: str = "low",
        metadata: dict[str, object] | None = None,
    ) -> None:
        created = AuditEventCreate(
            project_id=None,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            risk_level=risk_level,
            metadata=metadata or {},
        )
        self.recorded.append(created)
        self.events.append(
            AuditEventRead(
                id=uuid4(),
                created_at=datetime.now(UTC),
                **created.model_dump(),
            )
        )

    async def list_project_events(
        self,
        *,
        project_id: UUID,
        filters: AuditEventFilters,
    ) -> list[AuditEventRead]:
        self.project_filters.append(filters)
        return [
            event
            for event in self.events
            if event.project_id == project_id and _matches_filters(event, filters)
        ][: filters.limit]

    async def list_global_events(self, *, filters: AuditEventFilters) -> list[AuditEventRead]:
        self.global_filters.append(filters)
        return [event for event in self.events if _matches_filters(event, filters)][: filters.limit]


def _matches_filters(event: AuditEventRead, filters: AuditEventFilters) -> bool:
    if filters.project_id is not None and event.project_id != filters.project_id:
        return False
    if filters.actor_id is not None and event.actor_id != filters.actor_id:
        return False
    if filters.action is not None and event.action != filters.action:
        return False
    if filters.risk_level is not None and event.risk_level != filters.risk_level:
        return False
    if filters.result is not None and event.result != filters.result:
        return False
    if filters.target_type is not None and event.target_type != filters.target_type:
        return False
    if filters.created_from is not None and event.created_at < filters.created_from:
        return False
    return not (filters.created_to is not None and event.created_at > filters.created_to)


def make_account(*, is_super_admin: bool = False) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=uuid4(),
        status="active",
        is_super_admin=is_super_admin,
    )


def make_project(
    project_id: UUID | None = None,
    *,
    permissions: list[str],
) -> ProjectSummary:
    resolved_id = project_id or uuid4()
    return ProjectSummary(
        id=resolved_id,
        slug=f"project-{resolved_id.hex[:8]}",
        name="运维排障项目",
        status="active",
        roles=["project_admin"],
        permissions=permissions,
    )


def make_event(
    *,
    project_id: UUID | None,
    actor_id: UUID,
    action: str,
    risk_level: str,
    result: str = "success",
    target_type: str = "tool_gateway_invocation",
    created_at: datetime | None = None,
) -> AuditEventRead:
    return AuditEventRead(
        id=uuid4(),
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=f"target-{uuid4().hex[:8]}",
        result=result,
        risk_level=risk_level,
        metadata={"trace_id": "trace-123"},
        created_at=created_at or datetime.now(UTC),
    )


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    audit_store: InMemoryAuditEventStore,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
    return TestClient(app)


def test_project_audit_events_filter_by_action_risk_actor_time_and_scope() -> None:
    actor = make_account()
    project = make_project(permissions=["audit:view"])
    other_project = make_project(permissions=["audit:view"])
    now = datetime.now(UTC)
    matching = make_event(
        project_id=project.id,
        actor_id=actor.account_id,
        action="tool_gateway.invoke",
        risk_level="high",
        result="failure",
        created_at=now,
    )
    audit_store = InMemoryAuditEventStore(
        [
            matching,
            make_event(
                project_id=project.id,
                actor_id=actor.account_id,
                action="workflow.import_draft",
                risk_level="low",
                created_at=now,
            ),
            make_event(
                project_id=other_project.id,
                actor_id=actor.account_id,
                action="tool_gateway.invoke",
                risk_level="high",
                result="failure",
                created_at=now,
            ),
        ]
    )
    client = build_client(
        account=actor,
        provider=PermissionAwareProjectProvider([project]),
        audit_store=audit_store,
    )

    response = client.get(
        f"/api/v1/projects/{project.id}/audit/events",
        params={
            "actor_id": str(actor.account_id),
            "action": "tool_gateway.invoke",
            "risk_level": "high",
            "result": "failure",
            "created_from": (now - timedelta(seconds=5)).isoformat(),
            "created_to": (now + timedelta(seconds=5)).isoformat(),
            "limit": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["events"][0]["id"] == str(matching.id)
    assert payload["events"][0]["project_id"] == str(project.id)
    assert audit_store.recorded[-1].action == "audit.events.list"


def test_project_audit_events_enforce_project_permission_boundary() -> None:
    account = make_account()
    project_without_permission = make_project(permissions=["project:view"])
    unknown_project_id = uuid4()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project_without_permission]),
        audit_store=audit_store,
    )

    forbidden = client.get(f"/api/v1/projects/{project_without_permission.id}/audit/events")
    hidden = client.get(f"/api/v1/projects/{unknown_project_id}/audit/events")

    assert forbidden.status_code == 403
    assert hidden.status_code == 404


def test_global_audit_events_require_super_admin_and_support_project_filter() -> None:
    super_admin = make_account(is_super_admin=True)
    project = make_project(permissions=[])
    other_project = make_project(permissions=[])
    matching = make_event(
        project_id=project.id,
        actor_id=super_admin.account_id,
        action="tool_gateway.invoke",
        risk_level="critical",
    )
    audit_store = InMemoryAuditEventStore(
        [
            matching,
            make_event(
                project_id=other_project.id,
                actor_id=super_admin.account_id,
                action="tool_gateway.invoke",
                risk_level="critical",
            ),
        ]
    )
    client = build_client(
        account=super_admin,
        provider=PermissionAwareProjectProvider([]),
        audit_store=audit_store,
    )

    response = client.get(
        "/api/v1/global/audit/events",
        params={"project_id": str(project.id), "risk_level": "critical"},
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["events"][0]["id"] == str(matching.id)
    assert audit_store.recorded[-1].action == "global.audit.events.list"

    regular_client = build_client(
        account=make_account(),
        provider=PermissionAwareProjectProvider([]),
        audit_store=InMemoryAuditEventStore(),
    )
    regular_response = regular_client.get("/api/v1/global/audit/events")
    assert regular_response.status_code == 403


def test_global_audit_empty_query_records_global_event_without_project_scope() -> None:
    super_admin = make_account(is_super_admin=True)
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=super_admin,
        provider=PermissionAwareProjectProvider([]),
        audit_store=audit_store,
    )

    response = client.get("/api/v1/global/audit/events")

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert audit_store.recorded[-1].project_id is None
    assert audit_store.recorded[-1].action == "global.audit.events.list"


def test_audit_export_request_and_raw_trace_access_are_recorded() -> None:
    account = make_account()
    project = make_project(
        permissions=["audit:view", "audit:export", "audit:raw-trace:view"],
    )
    event = make_event(
        project_id=project.id,
        actor_id=account.account_id,
        action="tool_gateway.invoke",
        risk_level="high",
    )
    audit_store = InMemoryAuditEventStore([event])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        audit_store=audit_store,
    )

    export_response = client.post(
        f"/api/v1/projects/{project.id}/audit/export-requests",
        json={
            "reason": "quarterly security review",
            "filters": {"risk_level": "high", "action": "tool_gateway.invoke"},
        },
    )
    raw_response = client.post(
        f"/api/v1/projects/{project.id}/audit/raw-trace-access-requests",
        json={
            "reason": "incident RCA",
            "run_id": "run-123",
            "trace_id": "trace-123",
            "target_type": "tool_gateway_invocation",
            "target_id": "call-123",
        },
    )

    assert export_response.status_code == 200
    assert export_response.json()["status"] == "recorded"
    assert raw_response.status_code == 200
    assert raw_response.json()["status"] == "recorded"
    actions = [event.action for event in audit_store.recorded]
    assert "audit.export.request" in actions
    assert "audit.raw_trace.access_request" in actions
    export_event = next(
        event for event in audit_store.recorded if event.action == "audit.export.request"
    )
    assert export_event.metadata["reason"] == "quarterly security review"
    assert export_event.metadata["event_count"] == 1
