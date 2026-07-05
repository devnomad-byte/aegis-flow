import asyncio
import json
import logging
import socket
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
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
from backend.app.policy_center.runtime import ApprovalPolicyRuntimeEvaluator
from backend.app.policy_center.sqlalchemy_store import SqlAlchemyPolicyCenterStore
from backend.app.policy_gate.sqlalchemy_store import SqlAlchemyPolicyGateEventStore
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient
from backend.app.tool_gateway.service import ToolGatewayService
from backend.app.tool_gateway.sqlalchemy_store import SqlAlchemyToolInvocationStore
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.workflow_runtime.checkpointing import PostgresWorkflowCheckpointerProvider
from backend.app.workflow_runtime.input_payloads import (
    WorkflowInputEncryptor,
    runtime_safe_inputs,
)
from backend.app.workflow_runtime.runner import WorkflowRuntimeError, WorkflowRuntimeRunner
from backend.app.workflow_runtime.schemas import (
    WorkflowRunEventCreate,
    WorkflowRunQueueItemCreate,
    WorkflowRunQueueItemRead,
    WorkflowRunRequest,
    WorkflowRunUpdate,
)
from backend.app.workflow_runtime.sqlalchemy_store import (
    SqlAlchemyWorkflowRunEventStore,
    SqlAlchemyWorkflowRunStore,
)
from backend.app.workflows.sqlalchemy_store import SqlAlchemyWorkflowVersionStore

logger = logging.getLogger(__name__)


class WorkflowQueueNotifier(Protocol):
    async def notify_run_enqueued(
        self,
        *,
        project_id: UUID,
        run_id: str,
        queue_item_id: UUID,
    ) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class NoopWorkflowQueueNotifier:
    async def notify_run_enqueued(
        self,
        *,
        project_id: UUID,
        run_id: str,
        queue_item_id: UUID,
    ) -> None:
        return None

    async def close(self) -> None:
        return None


class RedisWorkflowQueueNotifier:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        password = settings.redis.password.get_secret_value()
        self._redis = Redis(
            host=settings.redis.host,
            port=settings.redis.port,
            password=password or None,
            db=settings.redis.database,
            decode_responses=True,
        )

    async def notify_run_enqueued(
        self,
        *,
        project_id: UUID,
        run_id: str,
        queue_item_id: UUID,
    ) -> None:
        payload = json.dumps(
            {
                "project_id": str(project_id),
                "run_id": run_id,
                "queue_item_id": str(queue_item_id),
            },
            separators=(",", ":"),
        )
        channel = self._settings.workflow_queue.redis_wakeup_channel
        try:
            await self._redis.publish(channel, payload)
            await self._redis.set(
                f"{channel}:last",
                payload,
                ex=self._settings.workflow_queue.redis_wakeup_ttl_seconds,
            )
        except RedisError:
            logger.warning("workflow queue Redis wakeup failed; PostgreSQL queue remains durable")

    async def close(self) -> None:
        await self._redis.aclose()


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
        self._input_encryptor = WorkflowInputEncryptor(
            secret=self._settings.workflow_queue.encryption_secret,
            key_ref=self._settings.workflow_queue.encryption_key_ref,
        )

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @property
    def input_encryptor(self) -> WorkflowInputEncryptor:
        return self._input_encryptor

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

    async def process_next_queue_item(self, *, worker_id: str) -> bool:
        async with self._session_factory() as session:
            run_store = SqlAlchemyWorkflowRunStore(session)
            queue_item = await run_store.claim_next_queue_item(
                worker_id=worker_id,
                lease_seconds=self._settings.workflow_queue.lease_seconds,
            )
            if queue_item is None:
                return False
            await run_store.mark_queue_item_running(
                queue_item_id=queue_item.id,
                worker_id=worker_id,
            )
            event_store = SqlAlchemyWorkflowRunEventStore(session)
            await self._record_queue_event(
                event_store,
                queue_item=queue_item,
                event_type="run.worker.claimed",
                status="running",
                message="workflow run claimed by durable worker",
            )
            try:
                await self._execute_queue_item(
                    session=session,
                    run_store=run_store,
                    event_store=event_store,
                    queue_item=queue_item,
                )
            except Exception as exc:
                await self._handle_queue_failure(
                    run_store=run_store,
                    event_store=event_store,
                    queue_item=queue_item,
                    exc=exc,
                )
            return True

    async def _execute_queue_item(
        self,
        *,
        session: AsyncSession,
        run_store: SqlAlchemyWorkflowRunStore,
        event_store: SqlAlchemyWorkflowRunEventStore,
        queue_item: WorkflowRunQueueItemRead,
    ) -> None:
        version_store = SqlAlchemyWorkflowVersionStore(session)
        version = await version_store.get_project_version(
            queue_item.project_id,
            queue_item.workflow_version_id,
        )
        run = await run_store.get_run(project_id=queue_item.project_id, run_id=queue_item.run_id)
        if version is None or run is None:
            raise WorkflowRuntimeError("workflow queue item references a missing run or version")
        if run.status == "cancelled":
            await run_store.complete_queue_item(queue_item_id=queue_item.id, status="cancelled")
            return
        decrypted_inputs = self._input_encryptor.decrypt(
            queue_item.encrypted_inputs,
            key_ref=queue_item.encryption_key_ref,
        )
        safe_inputs = runtime_safe_inputs(decrypted_inputs)
        runner = self._build_runner(session, run_store, event_store)
        result = await runner.run_existing(
            WorkflowRunRequest(
                project_id=queue_item.project_id,
                actor_id=queue_item.actor_id,
                version=version,
                inputs=safe_inputs,
                run_id=run.run_id,
                trace_id=run.trace_id,
            ),
            run,
        )
        await run_store.complete_queue_item(
            queue_item_id=queue_item.id,
            status="cancelled" if result.status == "cancelled" else "completed",
        )

    async def _handle_queue_failure(
        self,
        *,
        run_store: SqlAlchemyWorkflowRunStore,
        event_store: SqlAlchemyWorkflowRunEventStore,
        queue_item: WorkflowRunQueueItemRead,
        exc: Exception,
    ) -> None:
        backoff_seconds = self._next_backoff_seconds(queue_item)
        failed_item = await run_store.fail_queue_item(
            queue_item_id=queue_item.id,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            backoff_seconds=backoff_seconds,
        )
        if failed_item.status == "dead_letter":
            await self._mark_run_failed_from_queue_error(
                run_store=run_store,
                queue_item=queue_item,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            await self._record_queue_event(
                event_store,
                queue_item=queue_item,
                event_type="run.worker.dead_letter",
                status="failed",
                message="workflow run moved to durable queue dead letter",
                payload={
                    "attempt_count": failed_item.attempt_count,
                    "max_attempts": failed_item.max_attempts,
                    "error_type": exc.__class__.__name__,
                },
            )
            return
        await self._record_queue_event(
            event_store,
            queue_item=queue_item,
            event_type="run.worker.retry_scheduled",
            status="queued",
            message="workflow run retry scheduled by durable worker",
            payload={
                "attempt_count": failed_item.attempt_count,
                "max_attempts": failed_item.max_attempts,
                "backoff_seconds": backoff_seconds,
                "error_type": exc.__class__.__name__,
            },
        )

    async def _mark_run_failed_from_queue_error(
        self,
        *,
        run_store: SqlAlchemyWorkflowRunStore,
        queue_item: WorkflowRunQueueItemRead,
        error_type: str,
        error_message: str,
    ) -> None:
        run = await run_store.get_run(project_id=queue_item.project_id, run_id=queue_item.run_id)
        if run is None or run.status in {"success", "failed", "pending_approval", "cancelled"}:
            return
        await run_store.update_run(
            WorkflowRunUpdate(
                project_id=queue_item.project_id,
                run_id=queue_item.run_id,
                actor_id=queue_item.actor_id,
                status="failed",
                outputs_summary="",
                error_type=error_type,
                error_message=error_message,
            )
        )

    async def _record_queue_event(
        self,
        event_store: SqlAlchemyWorkflowRunEventStore,
        *,
        queue_item: WorkflowRunQueueItemRead,
        event_type: str,
        status: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        await event_store.record_event(
            WorkflowRunEventCreate(
                project_id=queue_item.project_id,
                actor_id=queue_item.actor_id,
                workflow_run_id=queue_item.workflow_run_id,
                workflow_version_id=queue_item.workflow_version_id,
                workflow_ref=queue_item.workflow_ref,
                run_id=queue_item.run_id,
                trace_id=queue_item.trace_id,
                event_type=event_type,
                status=status,
                message=message,
                payload_summary="durable workflow queue",
                payload=payload or {},
                created_by=queue_item.actor_id,
                updated_by=queue_item.actor_id,
            )
        )

    def _next_backoff_seconds(self, queue_item: WorkflowRunQueueItemRead) -> int:
        exponent = max(queue_item.attempt_count - 1, 0)
        return int(self._settings.workflow_queue.retry_backoff_base_seconds * (2**exponent))

    def _build_runner(
        self,
        session: AsyncSession,
        run_store: SqlAlchemyWorkflowRunStore,
        event_store: SqlAlchemyWorkflowRunEventStore,
    ) -> WorkflowRuntimeRunner:
        registry_store = SqlAlchemyToolRegistryStore(session)
        model_gateway_store = SqlAlchemyModelGatewayStore(session)
        approval_evaluator = ApprovalPolicyRuntimeEvaluator(
            policy_store=SqlAlchemyPolicyCenterStore(session),
            policy_gate_store=SqlAlchemyPolicyGateEventStore(session),
        )
        tool_gateway = ToolGatewayService(
            registry_store=registry_store,
            invocation_store=SqlAlchemyToolInvocationStore(session),
            audit_store=SqlAlchemyAuditEventStore(session),
            call_client=HttpMcpToolCallClient(),
            approval_evaluator=approval_evaluator,
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
                approval_evaluator=approval_evaluator,
            ),
            tool_gateway=tool_gateway,
            execution_gateway=ShellExecutionGatewayService(
                template_store=registry_store,
                invocation_store=SqlAlchemyShellInvocationStore(session),
                approval_evaluator=approval_evaluator,
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
    def __init__(
        self,
        worker: WorkflowRunWorker,
        *,
        settings: AppSettings | None = None,
        notifier: WorkflowQueueNotifier | None = None,
    ) -> None:
        self._worker = worker
        self._settings = settings or AppSettings()
        self._notifier = notifier or (
            RedisWorkflowQueueNotifier(self._settings)
            if self._settings.workflow_queue.redis_wakeup_enabled
            else NoopWorkflowQueueNotifier()
        )
        self._tasks: set[asyncio.Task[None]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._wake_event = asyncio.Event()
        self._worker_id = f"{socket.gethostname()}:{id(self)}"

    async def start(self) -> None:
        await self.reconcile_startup()
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._run_loop())

    async def reconcile_startup(self) -> dict[str, int]:
        async with self._worker.session_factory() as session:
            store = SqlAlchemyWorkflowRunStore(session)
            return await store.reconcile_stale_queue_items(worker_id=self._worker_id)

    async def submit(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        version_id: UUID,
        run_id: str,
        inputs: Mapping[str, object] | None = None,
    ) -> None:
        queue_item = await self._enqueue_queue_item(
            project_id=project_id,
            actor_id=actor_id,
            version_id=version_id,
            run_id=run_id,
            inputs=dict(inputs or {}),
        )
        await self._notifier.notify_run_enqueued(
            project_id=project_id,
            run_id=run_id,
            queue_item_id=queue_item.id,
        )
        self._wake_event.set()
        if self._loop_task is None or self._loop_task.done():
            task = asyncio.create_task(self._drain_available_queue())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def cancel(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        run_id: str,
        reason: str = "",
    ) -> None:
        async with self._worker.session_factory() as session:
            store = SqlAlchemyWorkflowRunStore(session)
            await store.cancel_queue_item(
                project_id=project_id,
                run_id=run_id,
                actor_id=actor_id,
                reason=reason,
            )

    async def _enqueue_queue_item(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        version_id: UUID,
        run_id: str,
        inputs: dict[str, object],
    ) -> WorkflowRunQueueItemRead:
        now = datetime.now(UTC)
        async with self._worker.session_factory() as session:
            store = SqlAlchemyWorkflowRunStore(session)
            run = await store.get_run(project_id=project_id, run_id=run_id)
            if run is None:
                raise WorkflowRuntimeError("workflow run must exist before queue enqueue")
            ciphertext = self._worker.input_encryptor.encrypt(inputs)
            return await store.enqueue_run_queue_item(
                WorkflowRunQueueItemCreate(
                    project_id=project_id,
                    actor_id=actor_id,
                    workflow_run_id=run.id,
                    workflow_version_id=version_id,
                    workflow_ref=run.workflow_ref,
                    run_id=run.run_id,
                    trace_id=run.trace_id,
                    encrypted_inputs=ciphertext,
                    encryption_key_ref=self._settings.workflow_queue.encryption_key_ref,
                    input_keys=sorted(str(key) for key in inputs),
                    max_attempts=self._settings.workflow_queue.max_attempts,
                    available_at=now,
                    expires_at=now
                    + timedelta(seconds=self._settings.workflow_queue.payload_ttl_seconds),
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )

    async def _run_loop(self) -> None:
        while True:
            await self._drain_available_queue()
            self._wake_event.clear()
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self._settings.workflow_queue.poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _drain_available_queue(self) -> None:
        while await self._worker.process_next_queue_item(worker_id=self._worker_id):
            await asyncio.sleep(0)

    async def shutdown(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self._notifier.close()
