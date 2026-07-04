import asyncio
import logging
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.audit.sqlalchemy_store import SqlAlchemyAuditEventStore
from backend.app.core.settings import AppSettings
from backend.app.execution.gateway import HttpExecutionGatewayService, ShellExecutionGatewayService
from backend.app.execution.sqlalchemy_store import (
    SqlAlchemyHttpInvocationStore,
    SqlAlchemyShellInvocationStore,
)
from backend.app.model_gateway.openai_compatible import OpenAICompatibleModelGatewayClient
from backend.app.model_gateway.runner import LlmNodeRunner
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from backend.app.observability.sqlalchemy_store import SqlAlchemyRuntimeTraceStore
from backend.app.policy_gate.sqlalchemy_store import SqlAlchemyPolicyGateEventStore
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient
from backend.app.tool_gateway.service import ToolGatewayService
from backend.app.tool_gateway.sqlalchemy_store import SqlAlchemyToolInvocationStore
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.workflow_runtime.checkpointing import PostgresWorkflowCheckpointerProvider
from backend.app.workflow_runtime.runner import WorkflowRuntimeError, WorkflowRuntimeRunner
from backend.app.workflow_runtime.schemas import WorkflowRunRequest
from backend.app.workflow_runtime.sqlalchemy_store import (
    SqlAlchemyWorkflowRunEventStore,
    SqlAlchemyWorkflowRunStore,
)
from backend.app.workflows.sqlalchemy_store import SqlAlchemyWorkflowVersionStore

logger = logging.getLogger(__name__)


class WorkflowRunWorker:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: AppSettings | None = None,
        http_egress_policy: EgressPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or AppSettings()
        self._http_egress_policy = http_egress_policy or EgressPolicy()

    async def run_queued(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        version_id: UUID,
        run_id: str,
        inputs: Mapping[str, object] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            version_store = SqlAlchemyWorkflowVersionStore(session)
            run_store = SqlAlchemyWorkflowRunStore(session)
            event_store = SqlAlchemyWorkflowRunEventStore(session)
            version = await version_store.get_project_version(project_id, version_id)
            run = await run_store.get_run(project_id=project_id, run_id=run_id)
            if version is None or run is None:
                logger.warning("workflow background run skipped because version or run is missing")
                return
            runner = self._build_runner(session, run_store, event_store)
            try:
                await runner.run_existing(
                    WorkflowRunRequest(
                        project_id=project_id,
                        actor_id=actor_id,
                        version=version,
                        inputs=dict(inputs or {}),
                        run_id=run.run_id,
                        trace_id=run.trace_id,
                    ),
                    run,
                )
            except WorkflowRuntimeError:
                raise
            except Exception:
                logger.exception("workflow background run failed unexpectedly")
                raise

    def _build_runner(
        self,
        session: AsyncSession,
        run_store: SqlAlchemyWorkflowRunStore,
        event_store: SqlAlchemyWorkflowRunEventStore,
    ) -> WorkflowRuntimeRunner:
        registry_store = SqlAlchemyToolRegistryStore(session)
        model_gateway_store = SqlAlchemyModelGatewayStore(session)
        tool_gateway = ToolGatewayService(
            registry_store=registry_store,
            invocation_store=SqlAlchemyToolInvocationStore(session),
            audit_store=SqlAlchemyAuditEventStore(session),
            call_client=HttpMcpToolCallClient(),
        )
        return WorkflowRuntimeRunner(
            run_store=run_store,
            policy_store=SqlAlchemyPolicyGateEventStore(session),
            trace_store=SqlAlchemyRuntimeTraceStore(session),
            llm_runner=LlmNodeRunner(
                policy_store=model_gateway_store,
                invocation_store=model_gateway_store,
                model_client=OpenAICompatibleModelGatewayClient(
                    self._settings.model_gateway.openai_compatible
                ),
                prompt_store=model_gateway_store,
            ),
            tool_gateway=tool_gateway,
            execution_gateway=ShellExecutionGatewayService(
                template_store=registry_store,
                invocation_store=SqlAlchemyShellInvocationStore(session),
            ),
            http_execution_gateway=HttpExecutionGatewayService(
                environment_store=registry_store,
                invocation_store=SqlAlchemyHttpInvocationStore(session),
                egress_policy=self._http_egress_policy,
            ),
            checkpointer_provider=PostgresWorkflowCheckpointerProvider(self._settings.database),
            event_store=event_store,
        )


class InProcessWorkflowRunScheduler:
    def __init__(self, worker: WorkflowRunWorker) -> None:
        self._worker = worker
        self._tasks: set[asyncio.Task[None]] = set()

    async def submit(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        version_id: UUID,
        run_id: str,
        inputs: Mapping[str, object] | None = None,
    ) -> None:
        task = asyncio.create_task(
            self._worker.run_queued(
                project_id=project_id,
                actor_id=actor_id,
                version_id=version_id,
                run_id=run_id,
                inputs=inputs,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
