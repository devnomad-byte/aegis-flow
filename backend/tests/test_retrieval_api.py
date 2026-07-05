from collections.abc import Iterable
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_retrieval_gateway_store,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.retrieval.schemas import (
    MemoryRunLessonQueryRequest,
    MemoryRunLessonQueryResponse,
    MemoryRunLessonResultRead,
    MemoryRunLessonTraceSummary,
    RetrievalCitation,
    RetrievalQueryRequest,
    RetrievalQueryResponse,
    RetrievalResultRead,
    RetrievalSubject,
    RetrievalTraceSummary,
)
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


class InMemoryRetrievalGatewayStore:
    def __init__(self) -> None:
        self.subjects: list[RetrievalSubject] = []
        self.memory_subjects: list[RetrievalSubject] = []

    async def query(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: RetrievalQueryRequest,
    ) -> RetrievalQueryResponse:
        self.subjects = subjects
        chunk_id = uuid4()
        return RetrievalQueryResponse(
            query_hash="query-hash-no-raw",
            results=[
                RetrievalResultRead(
                    chunk_id=chunk_id,
                    chunk_ref="child-0001-0001",
                    parent_chunk_id=uuid4(),
                    parent_chunk_ref="parent-0001",
                    score=0.42,
                    source="hybrid",
                    text_preview="sanitized 502 ingress context",
                    data_classification="internal",
                    environment="prod",
                    citation=RetrievalCitation(
                        knowledge_base_id=uuid4(),
                        document_id=uuid4(),
                        document_ref="runbook-502",
                        document_title="502 Runbook",
                        document_version_id=uuid4(),
                        document_version=1,
                        chunk_id=chunk_id,
                        chunk_ref="child-0001-0001",
                        parent_chunk_id=uuid4(),
                        parent_chunk_ref="parent-0001",
                        content_hash="chunk-hash",
                        s3_text_uri="s3://aegis-flow/runbook/chunk.txt",
                    ),
                )
            ],
            denied_count=0,
            trace_summary=RetrievalTraceSummary(
                retrieval_mode=request.retrieval_mode,
                prefilter_count=1,
                keyword_hit_count=1,
                vector_hit_count=1,
                fused_count=1,
                returned_count=1,
                denied_count=0,
                rerank_strategy="none",
                trace_id=request.trace_id,
            ),
        )

    async def query_run_lessons(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: MemoryRunLessonQueryRequest,
    ) -> MemoryRunLessonQueryResponse:
        self.memory_subjects = subjects
        lesson_id = uuid4()
        return MemoryRunLessonQueryResponse(
            query_hash="memory-query-hash-no-raw",
            denied_count=0,
            trace_summary=MemoryRunLessonTraceSummary(
                prefilter_count=1,
                keyword_hit_count=1,
                returned_count=1,
                denied_count=0,
                trace_id=request.trace_id,
            ),
            results=[
                MemoryRunLessonResultRead(
                    lesson_id=lesson_id,
                    lesson_ref="run-502:trace-502:shell_1",
                    title="Ingress rollback lesson",
                    summary="502 recovered with approved rollback",
                    workflow_id="ops_incident_triage",
                    workflow_run_id="run-502",
                    node_id="shell_1",
                    trace_id="trace-502",
                    severity="high",
                    data_classification="internal",
                    content_hash="sha256:lesson",
                    status="active",
                    score=1.0,
                    source="run_lesson_keyword",
                )
            ],
        )


class InMemoryAuditEventStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

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
        self.events.append(
            {
                "project_id": project_id,
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "result": result,
                "risk_level": risk_level,
                "metadata": metadata or {},
            }
        )


def test_retrieval_query_api_returns_citations_and_sanitized_audit() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["retrieval:query"], roles=["ops"])
    retrieval_store = InMemoryRetrievalGatewayStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        retrieval_store=retrieval_store,
        audit_store=audit_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/query",
        json={
            "query": "secret-looking 502 ingress question",
            "retrieval_mode": "hybrid",
            "top_k": 3,
            "trace_id": "trace-502",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["citation"]["document_ref"] == "runbook-502"
    assert body["trace_summary"]["trace_id"] == "trace-502"
    account_subject = RetrievalSubject(
        subject_type="account",
        subject_ref=f"account:{account.account_id}",
    )
    assert account_subject in retrieval_store.subjects
    assert RetrievalSubject(subject_type="role", subject_ref="role:ops") in retrieval_store.subjects
    assert [event["action"] for event in audit_store.events] == ["retrieval.query"]
    assert "secret-looking 502 ingress question" not in str(audit_store.events)


def test_retrieval_query_api_requires_permission() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=[], roles=["ops"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        retrieval_store=InMemoryRetrievalGatewayStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/query",
        json={"query": "502 ingress"},
    )

    assert response.status_code == 403


def test_memory_run_lesson_query_requires_retrieval_and_knowledge_permissions() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["retrieval:query"], roles=["ops"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        retrieval_store=InMemoryRetrievalGatewayStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/memory/run-lessons/query",
        json={"query": "502 ingress rollback"},
    )

    assert response.status_code == 403


def test_memory_run_lesson_query_api_returns_safe_summary_and_sanitized_audit() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["retrieval:query", "knowledge:view"], roles=["ops"])
    retrieval_store = InMemoryRetrievalGatewayStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        retrieval_store=retrieval_store,
        audit_store=audit_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/memory/run-lessons/query",
        json={"query": "secret-looking 502 ingress rollback", "top_k": 3, "trace_id": "trace-ui"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query_hash"] == "memory-query-hash-no-raw"
    assert body["results"][0]["lesson_ref"] == "run-502:trace-502:shell_1"
    assert "body" not in body["results"][0]
    assert retrieval_store.memory_subjects
    assert [event["action"] for event in audit_store.events] == [
        "retrieval.memory.run_lesson.query"
    ]
    rendered_audit = str(audit_store.events)
    assert "secret-looking 502 ingress rollback" not in rendered_audit
    assert audit_store.events[0]["metadata"] == {
        "query_hash": "memory-query-hash-no-raw",
        "result_count": 1,
        "denied_count": 0,
        "trace_id": "trace-ui",
    }


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    retrieval_store: InMemoryRetrievalGatewayStore,
    audit_store: InMemoryAuditEventStore,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_retrieval_gateway_store] = lambda: retrieval_store
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
    return TestClient(app)


def make_project(
    *,
    permissions: list[str],
    roles: list[str],
    project_id: UUID | None = None,
) -> ProjectSummary:
    resolved_id = project_id or uuid4()
    return ProjectSummary(
        id=resolved_id,
        slug=f"project-{resolved_id.hex[:8]}",
        name="运维排障项目",
        status="active",
        roles=roles,
        permissions=permissions,
    )
