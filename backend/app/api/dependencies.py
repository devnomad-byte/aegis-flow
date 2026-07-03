from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.sqlalchemy_store import SqlAlchemyAuditEventStore
from backend.app.audit.store import AuditEventStore
from backend.app.core.settings import AppSettings
from backend.app.db.session import get_async_session
from backend.app.global_command.sqlalchemy_store import SqlAlchemyGlobalCommandCenterStore
from backend.app.global_command.store import GlobalCommandCenterStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.iam.sqlalchemy_project_access import SqlAlchemyProjectAccessProvider
from backend.app.knowledge.object_store import build_knowledge_object_store
from backend.app.knowledge.sqlalchemy_store import SqlAlchemyKnowledgeIngestionStore
from backend.app.knowledge.store import KnowledgeIngestionStore
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from backend.app.retrieval.eval_store import RetrievalEvalStore
from backend.app.retrieval.milvus_client import build_milvus_retrieval_client
from backend.app.retrieval.sqlalchemy_eval_store import SqlAlchemyRetrievalEvalStore
from backend.app.retrieval.sqlalchemy_store import SqlAlchemyRetrievalGatewayStore
from backend.app.retrieval.store import RetrievalGatewayStore
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient, McpToolCallClient
from backend.app.tool_gateway.sqlalchemy_store import SqlAlchemyToolInvocationStore
from backend.app.tool_gateway.store import ToolInvocationStore
from backend.app.tool_registry.mcp_client import HttpMcpToolsClient, McpToolsClient
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


async def get_project_access_provider(
    session: AsyncSession = AsyncSessionDependency,
) -> ProjectAccessProvider:
    return await SqlAlchemyProjectAccessProvider.load(session)


def get_workflow_draft_store(
    session: AsyncSession = AsyncSessionDependency,
) -> WorkflowDraftStore:
    return SqlAlchemyWorkflowDraftStore(session)


def get_audit_event_store(
    session: AsyncSession = AsyncSessionDependency,
) -> AuditEventStore:
    return SqlAlchemyAuditEventStore(session)


def get_global_command_center_store(
    session: AsyncSession = AsyncSessionDependency,
) -> GlobalCommandCenterStore:
    return SqlAlchemyGlobalCommandCenterStore(session)


def get_knowledge_ingestion_store(
    session: AsyncSession = AsyncSessionDependency,
) -> KnowledgeIngestionStore:
    return SqlAlchemyKnowledgeIngestionStore(
        session,
        object_store=build_knowledge_object_store(AppSettings().s3),
    )


def get_retrieval_gateway_store(
    session: AsyncSession = AsyncSessionDependency,
) -> RetrievalGatewayStore:
    return SqlAlchemyRetrievalGatewayStore(
        session,
        milvus_client=build_milvus_retrieval_client(AppSettings().milvus),
    )


def get_retrieval_eval_store(
    session: AsyncSession = AsyncSessionDependency,
) -> RetrievalEvalStore:
    return SqlAlchemyRetrievalEvalStore(
        session,
        retrieval_store=SqlAlchemyRetrievalGatewayStore(
            session,
            milvus_client=build_milvus_retrieval_client(AppSettings().milvus),
        ),
    )


def get_model_gateway_store(
    session: AsyncSession = AsyncSessionDependency,
) -> SqlAlchemyModelGatewayStore:
    return SqlAlchemyModelGatewayStore(session)


def get_tool_registry_store(
    session: AsyncSession = AsyncSessionDependency,
) -> ToolRegistryStore:
    return SqlAlchemyToolRegistryStore(session)


def get_tool_invocation_store(
    session: AsyncSession = AsyncSessionDependency,
) -> ToolInvocationStore:
    return SqlAlchemyToolInvocationStore(session)


def get_mcp_tools_client() -> McpToolsClient:
    return HttpMcpToolsClient()


def get_mcp_tool_call_client() -> McpToolCallClient:
    return HttpMcpToolCallClient()


def get_mcp_egress_policy() -> EgressPolicy:
    return EgressPolicy()
