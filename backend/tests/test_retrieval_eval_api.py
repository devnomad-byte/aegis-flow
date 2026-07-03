from collections.abc import Iterable
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_retrieval_eval_store,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.retrieval.eval_store import (
    RetrievalEvalCaseCreate,
    RetrievalEvalCaseRead,
    RetrievalEvalDatasetCreate,
    RetrievalEvalDatasetRead,
    RetrievalEvalRunRead,
    RetrievalEvalRunRequest,
)
from backend.app.retrieval.schemas import RetrievalSubject
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


class InMemoryRetrievalEvalStore:
    def __init__(self) -> None:
        self.subjects: list[RetrievalSubject] = []

    async def create_dataset(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: RetrievalEvalDatasetCreate,
    ) -> RetrievalEvalDatasetRead:
        return RetrievalEvalDatasetRead(
            id=uuid4(),
            project_id=project_id,
            key=request.key,
            name=request.name,
            description=request.description,
            evaluation_scope=request.evaluation_scope,
            status="active",
        )

    async def list_datasets(self, project_id: UUID) -> list[RetrievalEvalDatasetRead]:
        return []

    async def create_case(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
        actor_id: UUID,
        request: RetrievalEvalCaseCreate,
    ) -> RetrievalEvalCaseRead | None:
        return RetrievalEvalCaseRead(
            id=uuid4(),
            project_id=project_id,
            dataset_id=dataset_id,
            case_ref=request.case_ref,
            query_text=request.query_text,
            expected_chunk_refs=request.expected_chunk_refs,
            expected_answer=request.expected_answer,
            tags=request.tags,
            expected_faithfulness=request.expected_faithfulness,
            status="active",
        )

    async def list_cases(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
    ) -> list[RetrievalEvalCaseRead]:
        return []

    async def run_dataset(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: RetrievalEvalRunRequest,
    ) -> RetrievalEvalRunRead | None:
        self.subjects = subjects
        return RetrievalEvalRunRead(
            id=uuid4(),
            project_id=project_id,
            dataset_id=dataset_id,
            actor_id=actor_id,
            status="completed",
            retrieval_mode=request.retrieval_mode,
            top_k=request.top_k,
            candidate_limit=request.candidate_limit,
            case_count=1,
            average_recall_at_k=1.0,
            average_mrr=1.0,
            average_context_precision=1.0,
            average_context_recall=1.0,
            average_faithfulness=0.9,
            leakage_count=0,
            deleted_visible_count=0,
            report={
                "cases": [
                    {
                        "case_ref": "ops-502-ingress",
                        "query_hash": "hash-only",
                        "returned_chunk_refs": ["child-a"],
                    }
                ]
            },
        )

    async def get_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RetrievalEvalRunRead | None:
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


def test_retrieval_eval_api_creates_dataset_case_and_run_without_raw_query_audit() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(
        permissions=["retrieval:eval:write", "retrieval:eval:view", "retrieval:query"],
        roles=["ops"],
    )
    eval_store = InMemoryRetrievalEvalStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        eval_store=eval_store,
        audit_store=audit_store,
    )

    dataset_response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/eval/datasets",
        json={
            "key": "ops-troubleshooting-v1",
            "name": "Ops Troubleshooting",
            "description": "Golden operations cases",
        },
    )
    dataset_id = dataset_response.json()["id"]
    case_response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/eval/datasets/{dataset_id}/cases",
        json={
            "case_ref": "ops-502-ingress",
            "query_text": "secret-looking 502 ingress recent deploy question",
            "expected_chunk_refs": ["child-a"],
            "expected_answer": "Check ingress logs",
            "tags": ["ops"],
            "expected_faithfulness": 0.9,
        },
    )
    run_response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/eval/datasets/{dataset_id}/runs",
        json={"top_k": 3, "retrieval_mode": "keyword"},
    )

    assert dataset_response.status_code == 201
    assert case_response.status_code == 201
    assert run_response.status_code == 201
    assert run_response.json()["average_recall_at_k"] == 1.0
    assert RetrievalSubject(subject_type="role", subject_ref="role:ops") in eval_store.subjects
    assert [event["action"] for event in audit_store.events] == [
        "retrieval.eval_dataset.create",
        "retrieval.eval_case.create",
        "retrieval.eval_run.create",
    ]
    assert "secret-looking 502 ingress recent deploy question" not in str(audit_store.events)


def test_retrieval_eval_run_requires_eval_view_and_retrieval_query_permissions() -> None:
    account = AccountPrincipal(account_id=uuid4(), status="active")
    project = make_project(permissions=["retrieval:eval:view"], roles=["ops"])
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        eval_store=InMemoryRetrievalEvalStore(),
        audit_store=InMemoryAuditEventStore(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/retrieval/eval/datasets/{uuid4()}/runs",
        json={"top_k": 3},
    )

    assert response.status_code == 403


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    eval_store: InMemoryRetrievalEvalStore,
    audit_store: InMemoryAuditEventStore,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_retrieval_eval_store] = lambda: eval_store
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
