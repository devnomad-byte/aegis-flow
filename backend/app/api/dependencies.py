from typing import cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.sqlalchemy_store import SqlAlchemyAuditEventStore
from backend.app.audit.store import AuditEventStore
from backend.app.core.settings import AppSettings
from backend.app.db.session import get_async_session
from backend.app.execution.gateway import HttpExecutionGatewayService, ShellExecutionGatewayService
from backend.app.execution.sqlalchemy_store import (
    SqlAlchemyHttpInvocationStore,
    SqlAlchemyShellInvocationStore,
)
from backend.app.global_command.sqlalchemy_store import SqlAlchemyGlobalCommandCenterStore
from backend.app.global_command.store import GlobalCommandCenterStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.iam.sqlalchemy_project_access import SqlAlchemyProjectAccessProvider
from backend.app.knowledge.object_store import build_knowledge_object_store
from backend.app.knowledge.sqlalchemy_store import SqlAlchemyKnowledgeIngestionStore
from backend.app.knowledge.store import KnowledgeIngestionStore
from backend.app.model_gateway.openai_compatible import OpenAICompatibleModelGatewayClient
from backend.app.model_gateway.runner import LlmNodeRunner
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from backend.app.observability.sqlalchemy_store import SqlAlchemyRuntimeTraceStore
from backend.app.policy_center.runtime import ApprovalPolicyRuntimeEvaluator
from backend.app.policy_center.sqlalchemy_store import SqlAlchemyPolicyCenterStore
from backend.app.policy_center.store import PolicyCenterStore
from backend.app.policy_gate.sqlalchemy_store import SqlAlchemyPolicyGateEventStore
from backend.app.project_admin.sqlalchemy_store import SqlAlchemyProjectAdminStore
from backend.app.project_admin.store import ProjectAdminStore
from backend.app.project_command.sqlalchemy_store import SqlAlchemyProjectCommandCenterStore
from backend.app.project_command.store import ProjectCommandCenterStore
from backend.app.retrieval.eval_store import RetrievalEvalStore
from backend.app.retrieval.milvus_client import build_milvus_retrieval_client
from backend.app.retrieval.sqlalchemy_eval_store import SqlAlchemyRetrievalEvalStore
from backend.app.retrieval.sqlalchemy_store import SqlAlchemyRetrievalGatewayStore
from backend.app.retrieval.store import RetrievalGatewayStore
from backend.app.runtime_approvals.sqlalchemy_store import SqlAlchemyRuntimeApprovalTaskStore
from backend.app.runtime_approvals.store import RuntimeApprovalTaskStore
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient, McpToolCallClient
from backend.app.tool_gateway.service import ToolGatewayService
from backend.app.tool_gateway.sqlalchemy_store import SqlAlchemyToolInvocationStore
from backend.app.tool_gateway.store import ToolInvocationStore
from backend.app.tool_registry.mcp_client import HttpMcpToolsClient, McpToolsClient
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.tool_registry.store import ToolRegistryStore
from backend.app.workflow_runtime.background import InProcessWorkflowRunScheduler
from backend.app.workflow_runtime.checkpoint_lifecycle import LangGraphCheckpointLifecycleService
from backend.app.workflow_runtime.checkpointing import (
    PostgresWorkflowCheckpointerProvider,
    WorkflowCheckpointerProvider,
)
from backend.app.workflow_runtime.runner import WorkflowRuntimeRunner
from backend.app.workflow_runtime.sqlalchemy_store import (
    SqlAlchemyWorkflowRunEventStore,
    SqlAlchemyWorkflowRunStore,
)
from backend.app.workflow_runtime.store import WorkflowRunEventStore, WorkflowRunStore
from backend.app.workflows.sqlalchemy_store import (
    SqlAlchemyWorkflowDraftStore,
    SqlAlchemyWorkflowVersionStore,
)
from backend.app.workflows.store import WorkflowDraftStore, WorkflowVersionStore

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


def get_workflow_version_store(
    session: AsyncSession = AsyncSessionDependency,
) -> WorkflowVersionStore:
    return SqlAlchemyWorkflowVersionStore(session)


def get_audit_event_store(
    session: AsyncSession = AsyncSessionDependency,
) -> AuditEventStore:
    return SqlAlchemyAuditEventStore(session)


def get_global_command_center_store(
    session: AsyncSession = AsyncSessionDependency,
) -> GlobalCommandCenterStore:
    return SqlAlchemyGlobalCommandCenterStore(session)


def get_project_command_center_store(
    session: AsyncSession = AsyncSessionDependency,
) -> ProjectCommandCenterStore:
    return SqlAlchemyProjectCommandCenterStore(session)


def get_policy_center_store(
    session: AsyncSession = AsyncSessionDependency,
) -> PolicyCenterStore:
    return SqlAlchemyPolicyCenterStore(session)


def get_project_admin_store(
    session: AsyncSession = AsyncSessionDependency,
) -> ProjectAdminStore:
    return SqlAlchemyProjectAdminStore(session)


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


def get_runtime_trace_store(
    session: AsyncSession = AsyncSessionDependency,
) -> SqlAlchemyRuntimeTraceStore:
    return SqlAlchemyRuntimeTraceStore(session)


def get_policy_gate_event_store(
    session: AsyncSession = AsyncSessionDependency,
) -> SqlAlchemyPolicyGateEventStore:
    return SqlAlchemyPolicyGateEventStore(session)


def get_tool_registry_store(
    session: AsyncSession = AsyncSessionDependency,
) -> ToolRegistryStore:
    return SqlAlchemyToolRegistryStore(session)


def get_tool_invocation_store(
    session: AsyncSession = AsyncSessionDependency,
) -> ToolInvocationStore:
    return SqlAlchemyToolInvocationStore(session)


def get_shell_invocation_store(
    session: AsyncSession = AsyncSessionDependency,
) -> SqlAlchemyShellInvocationStore:
    return SqlAlchemyShellInvocationStore(session)


def get_http_invocation_store(
    session: AsyncSession = AsyncSessionDependency,
) -> SqlAlchemyHttpInvocationStore:
    return SqlAlchemyHttpInvocationStore(session)


def get_runtime_approval_task_store(
    session: AsyncSession = AsyncSessionDependency,
) -> RuntimeApprovalTaskStore:
    return SqlAlchemyRuntimeApprovalTaskStore(session)


def get_mcp_tools_client() -> McpToolsClient:
    return HttpMcpToolsClient()


def get_mcp_tool_call_client() -> McpToolCallClient:
    return HttpMcpToolCallClient()


def get_workflow_run_store(
    session: AsyncSession = AsyncSessionDependency,
) -> WorkflowRunStore:
    return SqlAlchemyWorkflowRunStore(session)


def get_workflow_run_event_store(
    session: AsyncSession = AsyncSessionDependency,
) -> WorkflowRunEventStore:
    return SqlAlchemyWorkflowRunEventStore(session)


def get_workflow_run_scheduler(request: Request) -> InProcessWorkflowRunScheduler:
    return cast(InProcessWorkflowRunScheduler, request.app.state.workflow_run_scheduler)


ToolRegistryStoreDependency = Depends(get_tool_registry_store)
ToolInvocationStoreDependency = Depends(get_tool_invocation_store)
ShellInvocationStoreDependency = Depends(get_shell_invocation_store)
HttpInvocationStoreDependency = Depends(get_http_invocation_store)
AuditEventStoreDependency = Depends(get_audit_event_store)
McpToolCallClientDependency = Depends(get_mcp_tool_call_client)
ModelGatewayStoreDependency = Depends(get_model_gateway_store)
WorkflowRunStoreDependency = Depends(get_workflow_run_store)
WorkflowRunEventStoreDependency = Depends(get_workflow_run_event_store)
PolicyGateEventStoreDependency = Depends(get_policy_gate_event_store)
RuntimeTraceStoreDependency = Depends(get_runtime_trace_store)
PolicyCenterStoreDependency = Depends(get_policy_center_store)
RuntimeApprovalTaskStoreDependency = Depends(get_runtime_approval_task_store)


def get_workflow_checkpointer_provider() -> WorkflowCheckpointerProvider:
    return PostgresWorkflowCheckpointerProvider(AppSettings().database)


WorkflowCheckpointerProviderDependency = Depends(get_workflow_checkpointer_provider)


def get_checkpoint_lifecycle_service() -> LangGraphCheckpointLifecycleService:
    return LangGraphCheckpointLifecycleService(AppSettings().database)


CheckpointLifecycleServiceDependency = Depends(get_checkpoint_lifecycle_service)


def get_approval_policy_runtime_evaluator(
    policy_center_store: PolicyCenterStore = PolicyCenterStoreDependency,
    policy_gate_store: SqlAlchemyPolicyGateEventStore = PolicyGateEventStoreDependency,
) -> ApprovalPolicyRuntimeEvaluator:
    return ApprovalPolicyRuntimeEvaluator(
        policy_store=policy_center_store,
        policy_gate_store=policy_gate_store,
    )


ApprovalPolicyRuntimeEvaluatorDependency = Depends(get_approval_policy_runtime_evaluator)


def get_tool_gateway_service(
    registry_store: ToolRegistryStore = ToolRegistryStoreDependency,
    invocation_store: ToolInvocationStore = ToolInvocationStoreDependency,
    audit_store: AuditEventStore = AuditEventStoreDependency,
    call_client: McpToolCallClient = McpToolCallClientDependency,
    approval_evaluator: ApprovalPolicyRuntimeEvaluator = ApprovalPolicyRuntimeEvaluatorDependency,
) -> ToolGatewayService:
    return ToolGatewayService(
        registry_store=registry_store,
        invocation_store=invocation_store,
        audit_store=audit_store,
        call_client=call_client,
        approval_evaluator=approval_evaluator,
    )


def get_shell_execution_gateway_service(
    registry_store: ToolRegistryStore = ToolRegistryStoreDependency,
    invocation_store: SqlAlchemyShellInvocationStore = ShellInvocationStoreDependency,
    approval_evaluator: ApprovalPolicyRuntimeEvaluator = ApprovalPolicyRuntimeEvaluatorDependency,
    runtime_approval_store: RuntimeApprovalTaskStore = RuntimeApprovalTaskStoreDependency,
) -> ShellExecutionGatewayService:
    return ShellExecutionGatewayService(
        template_store=registry_store,
        invocation_store=invocation_store,
        approval_evaluator=approval_evaluator,
        runtime_approval_store=runtime_approval_store,
    )


def get_http_egress_policy() -> EgressPolicy:
    return EgressPolicy()


HttpEgressPolicyDependency = Depends(get_http_egress_policy)


def get_http_execution_gateway_service(
    registry_store: ToolRegistryStore = ToolRegistryStoreDependency,
    invocation_store: SqlAlchemyHttpInvocationStore = HttpInvocationStoreDependency,
    egress_policy: EgressPolicy = HttpEgressPolicyDependency,
) -> HttpExecutionGatewayService:
    return HttpExecutionGatewayService(
        environment_store=registry_store,
        invocation_store=invocation_store,
        egress_policy=egress_policy,
    )


def get_llm_node_runner(
    model_gateway_store: SqlAlchemyModelGatewayStore = ModelGatewayStoreDependency,
    approval_evaluator: ApprovalPolicyRuntimeEvaluator = ApprovalPolicyRuntimeEvaluatorDependency,
    runtime_approval_store: RuntimeApprovalTaskStore = RuntimeApprovalTaskStoreDependency,
) -> LlmNodeRunner:
    settings = AppSettings().model_gateway
    return LlmNodeRunner(
        policy_store=model_gateway_store,
        invocation_store=model_gateway_store,
        model_client=OpenAICompatibleModelGatewayClient(settings.openai_compatible),
        prompt_store=model_gateway_store,
        approval_evaluator=approval_evaluator,
        runtime_approval_store=runtime_approval_store,
    )


LlmNodeRunnerDependency = Depends(get_llm_node_runner)
ToolGatewayServiceDependency = Depends(get_tool_gateway_service)
ShellExecutionGatewayServiceDependency = Depends(get_shell_execution_gateway_service)
HttpExecutionGatewayServiceDependency = Depends(get_http_execution_gateway_service)


def get_workflow_runtime_runner(
    run_store: WorkflowRunStore = WorkflowRunStoreDependency,
    event_store: WorkflowRunEventStore = WorkflowRunEventStoreDependency,
    policy_store: SqlAlchemyPolicyGateEventStore = PolicyGateEventStoreDependency,
    trace_store: SqlAlchemyRuntimeTraceStore = RuntimeTraceStoreDependency,
    llm_runner: LlmNodeRunner = LlmNodeRunnerDependency,
    tool_gateway: ToolGatewayService = ToolGatewayServiceDependency,
    execution_gateway: ShellExecutionGatewayService = ShellExecutionGatewayServiceDependency,
    http_execution_gateway: HttpExecutionGatewayService = HttpExecutionGatewayServiceDependency,
    checkpointer_provider: WorkflowCheckpointerProvider = WorkflowCheckpointerProviderDependency,
) -> WorkflowRuntimeRunner:
    return WorkflowRuntimeRunner(
        run_store=run_store,
        policy_store=policy_store,
        trace_store=trace_store,
        llm_runner=llm_runner,
        tool_gateway=tool_gateway,
        execution_gateway=execution_gateway,
        http_execution_gateway=http_execution_gateway,
        checkpointer_provider=checkpointer_provider,
        event_store=event_store,
    )


def get_mcp_egress_policy() -> EgressPolicy:
    return EgressPolicy()
