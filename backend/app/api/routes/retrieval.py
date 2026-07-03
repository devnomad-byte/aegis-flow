from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_retrieval_eval_store,
    get_retrieval_gateway_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.retrieval.eval_store import (
    RetrievalEvalCaseCreate,
    RetrievalEvalCaseListResponse,
    RetrievalEvalCaseRead,
    RetrievalEvalDatasetCreate,
    RetrievalEvalDatasetListResponse,
    RetrievalEvalDatasetRead,
    RetrievalEvalRunRead,
    RetrievalEvalRunRequest,
    RetrievalEvalStore,
)
from backend.app.retrieval.schemas import (
    RetrievalQueryRequest,
    RetrievalQueryResponse,
    RetrievalSubject,
)
from backend.app.retrieval.store import RetrievalGatewayStore

router = APIRouter(prefix="/projects/{project_id}/retrieval", tags=["retrieval"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
RetrievalStore = Depends(get_retrieval_gateway_store)
RetrievalEval = Depends(get_retrieval_eval_store)
AuditStore = Depends(get_audit_event_store)


@router.post("/query", response_model=RetrievalQueryResponse)
async def query_retrieval_gateway(
    project_id: UUID,
    request: RetrievalQueryRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    retrieval_store: RetrievalGatewayStore = RetrievalStore,
    audit_store: AuditEventStore = AuditStore,
) -> RetrievalQueryResponse:
    project = _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:query",
    )
    subjects = _subjects_for_account(current_account, project)
    response = await retrieval_store.query(
        project_id=project_id,
        actor_id=current_account.account_id,
        subjects=subjects,
        request=request,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="retrieval.query",
        target_type="retrieval",
        target_id=response.query_hash,
        metadata={
            "query_hash": response.query_hash,
            "retrieval_mode": request.retrieval_mode,
            "result_count": len(response.results),
            "denied_count": response.denied_count,
            "trace_id": request.trace_id,
        },
    )
    return response


@router.post(
    "/eval/datasets",
    response_model=RetrievalEvalDatasetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_retrieval_eval_dataset(
    project_id: UUID,
    request: RetrievalEvalDatasetCreate,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    eval_store: RetrievalEvalStore = RetrievalEval,
    audit_store: AuditEventStore = AuditStore,
) -> RetrievalEvalDatasetRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:eval:write",
    )
    dataset = await eval_store.create_dataset(
        project_id=project_id,
        actor_id=current_account.account_id,
        request=request,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="retrieval.eval_dataset.create",
        target_type="retrieval_eval_dataset",
        target_id=str(dataset.id),
        metadata={"dataset_key": dataset.key, "evaluation_scope": dataset.evaluation_scope},
    )
    return dataset


@router.get("/eval/datasets", response_model=RetrievalEvalDatasetListResponse)
async def list_retrieval_eval_datasets(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    eval_store: RetrievalEvalStore = RetrievalEval,
) -> RetrievalEvalDatasetListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:eval:view",
    )
    datasets = await eval_store.list_datasets(project_id)
    return RetrievalEvalDatasetListResponse(datasets=datasets, count=len(datasets))


@router.post(
    "/eval/datasets/{dataset_id}/cases",
    response_model=RetrievalEvalCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_retrieval_eval_case(
    project_id: UUID,
    dataset_id: UUID,
    request: RetrievalEvalCaseCreate,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    eval_store: RetrievalEvalStore = RetrievalEval,
    audit_store: AuditEventStore = AuditStore,
) -> RetrievalEvalCaseRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:eval:write",
    )
    eval_case = await eval_store.create_case(
        project_id=project_id,
        dataset_id=dataset_id,
        actor_id=current_account.account_id,
        request=request,
    )
    if eval_case is None:
        raise _eval_dataset_not_found()
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="retrieval.eval_case.create",
        target_type="retrieval_eval_case",
        target_id=str(eval_case.id),
        metadata={
            "dataset_id": str(dataset_id),
            "case_ref": eval_case.case_ref,
            "expected_chunk_count": len(eval_case.expected_chunk_refs),
        },
    )
    return eval_case


@router.get(
    "/eval/datasets/{dataset_id}/cases",
    response_model=RetrievalEvalCaseListResponse,
)
async def list_retrieval_eval_cases(
    project_id: UUID,
    dataset_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    eval_store: RetrievalEvalStore = RetrievalEval,
) -> RetrievalEvalCaseListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:eval:view",
    )
    cases = await eval_store.list_cases(project_id=project_id, dataset_id=dataset_id)
    return RetrievalEvalCaseListResponse(cases=cases, count=len(cases))


@router.post(
    "/eval/datasets/{dataset_id}/runs",
    response_model=RetrievalEvalRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def run_retrieval_eval_dataset(
    project_id: UUID,
    dataset_id: UUID,
    request: RetrievalEvalRunRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    eval_store: RetrievalEvalStore = RetrievalEval,
    audit_store: AuditEventStore = AuditStore,
) -> RetrievalEvalRunRead:
    project = _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:eval:view",
    )
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:query",
    )
    run = await eval_store.run_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        actor_id=current_account.account_id,
        subjects=_subjects_for_account(current_account, project),
        request=request,
    )
    if run is None:
        raise _eval_dataset_not_found()
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="retrieval.eval_run.create",
        target_type="retrieval_eval_run",
        target_id=str(run.id),
        metadata={
            "dataset_id": str(dataset_id),
            "case_count": run.case_count,
            "retrieval_mode": run.retrieval_mode,
            "average_recall_at_k": run.average_recall_at_k,
            "average_mrr": run.average_mrr,
            "leakage_count": run.leakage_count,
            "deleted_visible_count": run.deleted_visible_count,
        },
    )
    return run


@router.get("/eval/runs/{run_id}", response_model=RetrievalEvalRunRead)
async def get_retrieval_eval_run(
    project_id: UUID,
    run_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    eval_store: RetrievalEvalStore = RetrievalEval,
) -> RetrievalEvalRunRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "retrieval:eval:view",
    )
    run = await eval_store.get_run(project_id=project_id, run_id=run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retrieval eval run not found",
        )
    return run


def _require_project_permission(
    project_access: ProjectAccessProvider,
    current_account: AccountPrincipal,
    project_id: UUID,
    required_permission: str,
) -> ProjectSummary:
    try:
        project = project_access.get_project_for_account(
            current_account,
            project_id,
            required_permission,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required project permission",
        ) from exc

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _subjects_for_account(
    current_account: AccountPrincipal,
    project: ProjectSummary,
) -> list[RetrievalSubject]:
    subjects = [
        RetrievalSubject(
            subject_type="account",
            subject_ref=f"account:{current_account.account_id}",
        ),
        RetrievalSubject(subject_type="project", subject_ref="project:members"),
    ]
    subjects.extend(
        RetrievalSubject(subject_type="role", subject_ref=f"role:{role}") for role in project.roles
    )
    return subjects


def _eval_dataset_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Retrieval eval dataset not found",
    )
