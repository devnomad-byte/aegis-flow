from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.execution.schemas import ShellInvocationCreate
from backend.app.execution.sqlalchemy_store import SqlAlchemyShellInvocationStore
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.policy_gate.schemas import PolicyGateEventCreate
from backend.app.policy_gate.sqlalchemy_store import SqlAlchemyPolicyGateEventStore
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_shell_invocation_store_records_ledger_and_runtime_span_by_project_scope() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        store = SqlAlchemyShellInvocationStore(session)
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()

        await store.record_invocation(
            make_shell_invocation(
                project_id=project_id,
                actor_id=actor_id,
                invocation_ref="shell-call-1",
                run_id="run-1",
                node_id="shell_1",
                trace_id="trace-1",
            )
        )
        await store.record_invocation(
            make_shell_invocation(
                project_id=project_id,
                actor_id=actor_id,
                invocation_ref="shell-call-2",
                run_id="run-2",
                node_id="shell_1",
                trace_id="trace-1",
            )
        )
        await store.record_invocation(
            make_shell_invocation(
                project_id=other_project_id,
                actor_id=actor_id,
                invocation_ref="shell-call-other-project",
                run_id="run-1",
                node_id="shell_1",
                trace_id="trace-1",
            )
        )

        invocations = await store.list_invocations(
            project_id=project_id,
            run_id="run-1",
            node_id="shell_1",
            trace_id="trace-1",
        )
        trace_spans = list(
            await session.scalars(
                select(RuntimeTraceSpan)
                .where(RuntimeTraceSpan.project_id == project_id)
                .order_by(RuntimeTraceSpan.created_at)
            )
        )

    await engine.dispose()

    assert len(invocations) == 1
    assert invocations[0].project_id == project_id
    assert invocations[0].invocation_ref == "shell-call-1"
    assert [span.span_id for span in trace_spans] == ["shell:shell-call-1", "shell:shell-call-2"]
    assert trace_spans[0].component == "shell_runner"
    assert trace_spans[0].source_type == "shell_runner_invocation"
    assert trace_spans[0].attributes["shell.template_ref"] == "k8s-log-collector"


@pytest.mark.asyncio
async def test_policy_gate_store_records_event_and_runtime_span_by_project_scope() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        store = SqlAlchemyPolicyGateEventStore(session)
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()

        await store.record_event(
            make_policy_event(
                project_id=project_id,
                actor_id=actor_id,
                event_ref="policy-event-1",
                run_id="run-1",
                node_id="shell_1",
                trace_id="trace-1",
            )
        )
        await store.record_event(
            make_policy_event(
                project_id=project_id,
                actor_id=actor_id,
                event_ref="policy-event-2",
                run_id="run-2",
                node_id="shell_1",
                trace_id="trace-1",
            )
        )
        await store.record_event(
            make_policy_event(
                project_id=other_project_id,
                actor_id=actor_id,
                event_ref="policy-event-other-project",
                run_id="run-1",
                node_id="shell_1",
                trace_id="trace-1",
            )
        )

        events = await store.list_events(
            project_id=project_id,
            run_id="run-1",
            node_id="shell_1",
            trace_id="trace-1",
        )
        trace_spans = list(
            await session.scalars(
                select(RuntimeTraceSpan)
                .where(RuntimeTraceSpan.project_id == project_id)
                .order_by(RuntimeTraceSpan.created_at)
            )
        )

    await engine.dispose()

    assert len(events) == 1
    assert events[0].project_id == project_id
    assert events[0].event_ref == "policy-event-1"
    assert [span.span_id for span in trace_spans] == [
        "policy:policy-event-1",
        "policy:policy-event-2",
    ]
    assert trace_spans[0].component == "policy_engine"
    assert trace_spans[0].source_type == "policy_gate_event"
    assert trace_spans[0].attributes["policy.decision"] == "approval_required"


def test_shell_invocation_create_rejects_raw_command_and_raw_output_fields() -> None:
    payload = make_shell_invocation(
        project_id=uuid4(),
        actor_id=uuid4(),
        invocation_ref="shell-call-raw",
        run_id="run-1",
        node_id="shell_1",
        trace_id="trace-1",
    ).model_dump()
    payload["raw_command"] = "kubectl get secret"
    payload["stdout"] = "token=raw"
    payload["stderr"] = "password=hunter2"
    payload["secret_lease_ref"] = "lease-raw"

    with pytest.raises(ValidationError):
        ShellInvocationCreate.model_validate(payload)


def test_policy_gate_event_create_rejects_raw_policy_input() -> None:
    payload = make_policy_event(
        project_id=uuid4(),
        actor_id=uuid4(),
        event_ref="policy-event-raw",
        run_id="run-1",
        node_id="shell_1",
        trace_id="trace-1",
    ).model_dump()
    payload["policy_input"] = {"password": "hunter2"}
    payload["secret"] = "raw"

    with pytest.raises(ValidationError):
        PolicyGateEventCreate.model_validate(payload)


def make_shell_invocation(
    *,
    project_id: UUID,
    actor_id: UUID,
    invocation_ref: str,
    run_id: str,
    node_id: str,
    trace_id: str,
) -> ShellInvocationCreate:
    return ShellInvocationCreate(
        project_id=project_id,
        actor_id=actor_id,
        invocation_ref=invocation_ref,
        template_ref="k8s-log-collector",
        template_version=3,
        command_hash="sha256:rendered-command",
        sandbox_image="capievo/runtime-sandbox-base:latest",
        sandbox_image_digest="sha256:image-digest",
        egress_profile_ref="egress-dev",
        egress_proxy_mode="envoy",
        network_mode="aegis-egress-dev",
        workflow_ref="incident-response",
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        status="success",
        exit_code=0,
        duration_ms=211,
        resource_usage={"cpu_seconds": 0.32, "memory_peak_bytes": 12_345_678},
        stdout_summary="collected 10 lines",
        stderr_summary="",
        created_by=actor_id,
        updated_by=actor_id,
    )


def make_policy_event(
    *,
    project_id: UUID,
    actor_id: UUID,
    event_ref: str,
    run_id: str,
    node_id: str,
    trace_id: str,
) -> PolicyGateEventCreate:
    return PolicyGateEventCreate(
        project_id=project_id,
        actor_id=actor_id,
        event_ref=event_ref,
        gate_ref="tool-preflight",
        policy_ref="ops-prod-risk",
        rule_ref="require-approval-for-shell",
        target_type="shell_template",
        target_ref="k8s-log-collector@3",
        workflow_ref="incident-response",
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        decision="approval_required",
        risk_level="critical",
        approval_required=True,
        approval_task_ref="approval-123",
        reason_summary="requires approval",
        duration_ms=17,
        created_by=actor_id,
        updated_by=actor_id,
    )
