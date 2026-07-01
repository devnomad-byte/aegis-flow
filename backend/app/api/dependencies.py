from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.sqlalchemy_store import SqlAlchemyAuditEventStore
from backend.app.audit.store import AuditEventStore
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.tool_registry.store import ToolRegistryStore
from backend.app.workflows.sqlalchemy_store import SqlAlchemyWorkflowDraftStore
from backend.app.workflows.store import WorkflowDraftStore

AsyncSessionDependency = Depends(get_async_session)


def get_current_account() -> AccountPrincipal:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def get_project_access_provider() -> ProjectAccessProvider:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Project access provider is not configured",
    )


def get_workflow_draft_store(
    session: AsyncSession = AsyncSessionDependency,
) -> WorkflowDraftStore:
    return SqlAlchemyWorkflowDraftStore(session)


def get_audit_event_store(
    session: AsyncSession = AsyncSessionDependency,
) -> AuditEventStore:
    return SqlAlchemyAuditEventStore(session)


def get_tool_registry_store(
    session: AsyncSession = AsyncSessionDependency,
) -> ToolRegistryStore:
    return SqlAlchemyToolRegistryStore(session)
