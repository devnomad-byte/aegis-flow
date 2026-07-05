from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_knowledge_ingestion_store,
    get_project_access_provider,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.knowledge.schemas import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseRead,
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentImportResult,
    KnowledgeDocumentRead,
    KnowledgeDocumentVersionRead,
    RunLessonCreateRequest,
    RunLessonRead,
)
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


class InMemoryKnowledgeIngestionStore:
    def __init__(self, allowed_knowledge_base_id: UUID) -> None:
        self.allowed_knowledge_base_id = allowed_knowledge_base_id
        self.imports: list[KnowledgeDocumentImportResult] = []
        self.deleted_ids: list[UUID] = []
        self.bases: list[KnowledgeBaseRead] = []
        self.run_lessons: list[RunLessonRead] = []

    async def create_knowledge_base(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: KnowledgeBaseCreateRequest,
    ) -> KnowledgeBaseRead:
        now = datetime.now(UTC)
        knowledge_base = KnowledgeBaseRead(
            id=self.allowed_knowledge_base_id,
            project_id=project_id,
            key=request.key,
            name=request.name,
            description=request.description,
            purpose=request.purpose,
            data_classification=request.data_classification,
            environment=request.environment,
            visibility=request.visibility,
            retention_policy_ref=request.retention_policy_ref,
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.bases.append(knowledge_base)
        return knowledge_base

    async def list_knowledge_bases(self, project_id: UUID) -> list[KnowledgeBaseRead]:
        return [
            knowledge_base
            for knowledge_base in self.bases
            if knowledge_base.project_id == project_id
        ]

    async def import_text_document(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        actor_id: UUID,
        request: KnowledgeDocumentImportRequest,
    ) -> KnowledgeDocumentImportResult | None:
        if knowledge_base_id != self.allowed_knowledge_base_id:
            return None
        now = datetime.now(UTC)
        document = KnowledgeDocumentRead(
            id=uuid4(),
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            document_ref=request.document_ref,
            title=request.title,
            source_type=request.content_format,
            source_uri=request.source_uri,
            current_version=1,
            data_classification=request.data_classification,
            acl_policy_ref=request.acl_policy_ref,
            status="active",
            is_deleted=False,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        version = KnowledgeDocumentVersionRead(
            id=uuid4(),
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            version=1,
            content_hash="hash-no-body",
            source_hash="source-hash-no-body",
            source_mime_type="text/markdown",
            source_size_bytes=len(request.content.encode()),
            s3_original_uri="s3://aegis-flow/original.txt",
            s3_normalized_uri="s3://aegis-flow/normalized.txt",
            ingestion_status="ready",
            ingestion_error="",
            chunk_count=2,
            indexed_chunk_count=0,
            status="active",
            is_deleted=False,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        result = KnowledgeDocumentImportResult(
            status="created",
            document=document,
            version=version,
            chunk_count=2,
            content_hash=version.content_hash,
        )
        self.imports.append(result)
        return result

    async def list_documents(
        self,
        project_id: UUID,
        knowledge_base_id: UUID,
    ) -> list[KnowledgeDocumentRead]:
        if knowledge_base_id != self.allowed_knowledge_base_id:
            return []
        return [
            imported.document
            for imported in self.imports
            if imported.document.project_id == project_id
            and imported.document.id not in self.deleted_ids
        ]

    async def delete_document(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        document_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeDocumentRead | None:
        if knowledge_base_id != self.allowed_knowledge_base_id:
            return None
        for imported in self.imports:
            if imported.document.project_id == project_id and imported.document.id == document_id:
                self.deleted_ids.append(document_id)
                return imported.document.model_copy(
                    update={"status": "deleted", "is_deleted": True, "updated_by": actor_id}
                )
        return None

    async def create_run_lesson(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: RunLessonCreateRequest,
    ) -> RunLessonRead:
        now = datetime.now(UTC)
        lesson = RunLessonRead(
            id=uuid4(),
            project_id=project_id,
            lesson_ref=request.lesson_ref,
            title=request.title,
            summary=request.summary,
            body=request.body,
            workflow_id=request.workflow_id,
            workflow_run_id=request.workflow_run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            severity=request.severity,
            data_classification=request.data_classification,
            milvus_collection="",
            milvus_vector_id="",
            content_hash="sha256:test-lesson",
            status="active",
            is_deleted=False,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.run_lessons.append(lesson)
        return lesson

    async def list_run_lessons(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 20,
    ) -> list[RunLessonRead]:
        lessons = [
            lesson
            for lesson in self.run_lessons
            if lesson.project_id == project_id
            and (run_id is None or lesson.workflow_run_id == run_id)
            and (trace_id is None or lesson.trace_id == trace_id)
        ]
        return lessons[:limit]


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


def test_knowledge_base_create_and_list_api_records_sanitized_audit() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:write", "knowledge:view"])
    store = InMemoryKnowledgeIngestionStore(uuid4())
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=store,
        audit_store=audit_store,
    )

    create_response = client.post(
        f"/api/v1/projects/{project.id}/knowledge/bases",
        json={
            "key": "ops-runbooks",
            "name": "Ops Runbooks",
            "description": "contains secret-looking text that must not enter audit",
            "purpose": "project_knowledge",
            "data_classification": "internal",
            "environment": "prod",
        },
    )
    list_response = client.get(f"/api/v1/projects/{project.id}/knowledge/bases")

    assert create_response.status_code == 201
    assert create_response.json()["key"] == "ops-runbooks"
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert list_response.json()["knowledge_bases"][0]["name"] == "Ops Runbooks"
    assert [event["action"] for event in audit_store.events] == [
        "knowledge.base.create",
        "knowledge.base.list",
    ]
    assert "secret-looking text" not in str(audit_store.events)


def test_knowledge_base_list_requires_view_permission() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:write"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=InMemoryKnowledgeIngestionStore(uuid4()),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.get(f"/api/v1/projects/{project.id}/knowledge/bases")

    assert response.status_code == 403


def test_knowledge_import_list_and_delete_api_records_sanitized_audit() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:write", "knowledge:view"])
    knowledge_base_id = uuid4()
    store = InMemoryKnowledgeIngestionStore(knowledge_base_id)
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=store,
        audit_store=audit_store,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/knowledge/bases/{knowledge_base_id}/documents/import-text",
        json={
            "document_ref": "runbook-502",
            "title": "502 Runbook",
            "content_format": "markdown",
            "content": "# 502\n\nsecret-looking text should not enter audit",
        },
    )
    assert response.status_code == 201
    document_id = response.json()["document"]["id"]

    list_response = client.get(
        f"/api/v1/projects/{project.id}/knowledge/bases/{knowledge_base_id}/documents"
    )
    delete_response = client.delete(
        f"/api/v1/projects/{project.id}/knowledge/bases/{knowledge_base_id}/documents/{document_id}"
    )
    list_after_delete_response = client.get(
        f"/api/v1/projects/{project.id}/knowledge/bases/{knowledge_base_id}/documents"
    )

    assert list_response.status_code == 200
    assert len(list_response.json()["documents"]) == 1
    assert delete_response.status_code == 200
    assert list_after_delete_response.json()["documents"] == []
    assert [event["action"] for event in audit_store.events] == [
        "knowledge.document.import",
        "knowledge.document.list",
        "knowledge.document.delete",
        "knowledge.document.list",
    ]
    assert "secret-looking text" not in str(audit_store.events)


def test_knowledge_import_requires_write_permission() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:view"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=InMemoryKnowledgeIngestionStore(uuid4()),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/knowledge/bases/{uuid4()}/documents/import-text",
        json={
            "document_ref": "runbook",
            "title": "Runbook",
            "content_format": "text",
            "content": "hello",
        },
    )

    assert response.status_code == 403


def test_knowledge_import_returns_404_for_unknown_knowledge_base() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:write"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=InMemoryKnowledgeIngestionStore(uuid4()),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/knowledge/bases/{uuid4()}/documents/import-text",
        json={
            "document_ref": "runbook",
            "title": "Runbook",
            "content_format": "text",
            "content": "hello",
        },
    )

    assert response.status_code == 404


def test_run_lesson_create_and_list_api_records_sanitized_audit() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:write", "knowledge:view"])
    store = InMemoryKnowledgeIngestionStore(uuid4())
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=store,
        audit_store=audit_store,
    )

    create_response = client.post(
        f"/api/v1/projects/{project.id}/knowledge/run-lessons",
        json={
            "lesson_ref": "run-ui:trace-ui:shell_1",
            "title": "Shell recovery lesson",
            "summary": "Approved resume succeeded token=raw-secret-token",
            "body": "Use approved shell template only password=raw-password",
            "workflow_id": "ops_incident_triage",
            "workflow_run_id": "run-ui",
            "node_id": "shell_1",
            "trace_id": "trace-ui",
            "severity": "high",
            "data_classification": "internal",
        },
    )
    list_response = client.get(
        f"/api/v1/projects/{project.id}/knowledge/run-lessons?run_id=run-ui&trace_id=trace-ui"
    )

    assert create_response.status_code == 201
    assert create_response.json()["lesson_ref"] == "run-ui:trace-ui:shell_1"
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert [event["action"] for event in audit_store.events] == [
        "knowledge.run_lesson.create",
        "knowledge.run_lesson.list",
    ]
    rendered_audit = str(audit_store.events)
    assert "raw-secret-token" not in rendered_audit
    assert "raw-password" not in rendered_audit
    assert audit_store.events[0]["metadata"] == {
        "lesson_ref": "run-ui:trace-ui:shell_1",
        "workflow_run_id": "run-ui",
        "trace_id": "trace-ui",
        "node_id": "shell_1",
        "severity": "high",
        "data_classification": "internal",
    }


def test_run_lesson_create_requires_knowledge_write_permission() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:view"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=InMemoryKnowledgeIngestionStore(uuid4()),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/knowledge/run-lessons",
        json={
            "lesson_ref": "run-ui:trace-ui",
            "title": "Shell recovery lesson",
            "summary": "Approved resume succeeded",
            "workflow_run_id": "run-ui",
            "trace_id": "trace-ui",
        },
    )

    assert response.status_code == 403


def test_run_lesson_list_requires_knowledge_view_permission() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["knowledge:write"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        knowledge_store=InMemoryKnowledgeIngestionStore(uuid4()),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.get(f"/api/v1/projects/{project.id}/knowledge/run-lessons")

    assert response.status_code == 403


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    knowledge_store: InMemoryKnowledgeIngestionStore,
    audit_store: InMemoryAuditEventStore,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_knowledge_ingestion_store] = lambda: knowledge_store
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
    return TestClient(app)


def make_project(
    *,
    permissions: list[str],
    project_id: UUID | None = None,
) -> ProjectSummary:
    resolved_id = project_id or uuid4()
    return ProjectSummary(
        id=resolved_id,
        slug=f"project-{resolved_id.hex[:8]}",
        name="运维排障项目",
        status="active",
        roles=["knowledge_admin"],
        permissions=permissions,
    )
