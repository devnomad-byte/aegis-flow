from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_retrieval_gateway_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
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
