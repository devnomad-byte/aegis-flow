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
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentImportResult,
    KnowledgeDocumentRead,
    KnowledgeDocumentVersionRead,
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
