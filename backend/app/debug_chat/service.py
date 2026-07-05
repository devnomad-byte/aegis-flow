from hashlib import sha256
from typing import Any
from uuid import UUID

from backend.app.debug_chat.schemas import (
    DebugChatEvidenceRead,
    DebugChatFailedNodeRead,
    DebugChatFindingRead,
    DebugChatRecommendedActionRead,
    DebugChatRunDiagnosisRequest,
    DebugChatRunDiagnosisResponse,
    DebugChatRunScopeRead,
    DebugChatSourceCountsRead,
)
from backend.app.observability.sqlalchemy_store import SqlAlchemyRuntimeTraceStore
from backend.app.security.redaction import redact_sensitive_text
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCheckpointRead,
    WorkflowRunEventRead,
    WorkflowRunRead,
)
from backend.app.workflow_runtime.store import WorkflowRunEventStore, WorkflowRunStore

FAILURE_STATUSES = {"failed", "denied", "error", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "cancel_requested", "pending_approval"}
TERMINAL_STATUSES = {"success", "failed", "cancelled"}
SPAN_SUMMARY_KEYS = (
    "error_message",
    "schema_validation_error",
    "output_summary",
    "input_summary",
    "tool.ref",
    "tool.policy_decision",
    "tool.risk_level",
    "shell.policy_decision",
)


class DebugChatRunNotFoundError(Exception):
    pass


class DebugChatTraceMismatchError(Exception):
    pass


class DebugChatRunDiagnosisService:
    def __init__(
        self,
        *,
        run_store: WorkflowRunStore,
        event_store: WorkflowRunEventStore,
        trace_store: SqlAlchemyRuntimeTraceStore,
    ) -> None:
        self._run_store = run_store
        self._event_store = event_store
        self._trace_store = trace_store

    async def diagnose_run(
        self,
        *,
        project_id: UUID,
        request: DebugChatRunDiagnosisRequest,
    ) -> DebugChatRunDiagnosisResponse:
        run = await self._run_store.get_run(project_id=project_id, run_id=request.run_id)
        if run is None:
            raise DebugChatRunNotFoundError
        trace_id = request.trace_id or run.trace_id
        if request.trace_id and request.trace_id != run.trace_id:
            raise DebugChatTraceMismatchError

        checkpoints = await self._run_store.list_checkpoints(
            project_id=project_id,
            run_id=run.run_id,
        )
        events = await self._event_store.list_events(
            project_id=project_id,
            run_id=run.run_id,
            after_sequence=0,
            limit=200,
        )
        spans = await self._trace_store.list_spans(
            project_id=project_id,
            run_id=run.run_id,
            trace_id=trace_id,
            limit=500,
        )

        failed_node = _find_failed_node(
            run=run,
            checkpoints=checkpoints,
            events=events,
            spans=spans,
        )
        evidence = _build_evidence(run=run, checkpoints=checkpoints, events=events, spans=spans)
        findings = _build_findings(run=run, failed_node=failed_node, evidence=evidence)
        actions = _build_recommended_actions(run=run, failed_node=failed_node)
        return DebugChatRunDiagnosisResponse(
            scope=DebugChatRunScopeRead(
                project_id=project_id,
                workflow_version_id=run.workflow_version_id,
                workflow_ref=run.workflow_ref,
                run_id=run.run_id,
                trace_id=trace_id,
                run_status=run.status,
            ),
            answer=_build_answer(run=run, failed_node=failed_node),
            failed_node=failed_node,
            findings=findings,
            recommended_actions=actions,
            evidence=evidence,
            source_counts=DebugChatSourceCountsRead(
                checkpoints=len(checkpoints),
                runtime_events=len(events),
                runtime_spans=len(spans),
            ),
        )


def question_hash(question: str) -> str:
    return sha256(question.encode("utf-8")).hexdigest()


def _find_failed_node(
    *,
    run: WorkflowRunRead,
    checkpoints: list[WorkflowRunCheckpointRead],
    events: list[WorkflowRunEventRead],
    spans: list[Any],
) -> DebugChatFailedNodeRead | None:
    for checkpoint in reversed(checkpoints):
        if checkpoint.status in FAILURE_STATUSES:
            return DebugChatFailedNodeRead(
                node_id=checkpoint.node_id,
                node_type=checkpoint.node_type,
                status=checkpoint.status,
                error_type=_safe_text(checkpoint.error_type),
                error_message=_safe_text(checkpoint.error_message),
                source="checkpoint",
            )
    for span in spans:
        if span.status in FAILURE_STATUSES:
            return DebugChatFailedNodeRead(
                node_id=span.node_id,
                node_type=_node_type_from_span(span),
                status=span.status,
                error_type=_safe_text(span.component),
                error_message=_safe_text(_span_summary(span.attributes)),
                source="runtime_span",
            )
    for event in reversed(events):
        if event.status in FAILURE_STATUSES or "failed" in event.event_type:
            return DebugChatFailedNodeRead(
                node_id=event.node_id,
                node_type=event.node_type,
                status=event.status or event.event_type,
                error_type=_safe_text(event.event_type),
                error_message=_safe_text(event.message or event.payload_summary),
                source="runtime_event",
            )
    if run.status == "pending_approval" and run.pending_approval:
        return DebugChatFailedNodeRead(
            node_id=_safe_text(run.pending_approval.get("node_id", "")),
            node_type="human_approval",
            status="pending_approval",
            error_type="ApprovalRequired",
            error_message=_safe_text(run.pending_approval.get("message", "")),
            source="workflow_run",
        )
    if run.status in FAILURE_STATUSES:
        return DebugChatFailedNodeRead(
            node_id="",
            node_type="workflow",
            status=run.status,
            error_type=_safe_text(run.error_type),
            error_message=_safe_text(run.error_message),
            source="workflow_run",
        )
    return None


def _build_evidence(
    *,
    run: WorkflowRunRead,
    checkpoints: list[WorkflowRunCheckpointRead],
    events: list[WorkflowRunEventRead],
    spans: list[Any],
) -> list[DebugChatEvidenceRead]:
    evidence = [
        DebugChatEvidenceRead(
            source="workflow_run",
            ref_id=run.run_id,
            status=run.status,
            summary=_safe_text(run.error_message or run.outputs_summary or run.inputs_summary),
        )
    ]
    for checkpoint in checkpoints:
        if checkpoint.status in FAILURE_STATUSES or checkpoint.status == "pending_approval":
            evidence.append(
                DebugChatEvidenceRead(
                    source="checkpoint",
                    ref_id=f"checkpoint:{checkpoint.node_id}",
                    node_id=checkpoint.node_id,
                    status=checkpoint.status,
                    summary=_safe_text(
                        checkpoint.error_message
                        or checkpoint.error_type
                        or _summary_from_mapping(checkpoint.output)
                        or checkpoint.status
                    ),
                )
            )
    for event in events:
        if event.status in FAILURE_STATUSES or "failed" in event.event_type:
            evidence.append(
                DebugChatEvidenceRead(
                    source="runtime_event",
                    ref_id=f"event:{event.sequence}",
                    node_id=event.node_id,
                    status=event.status,
                    summary=_safe_text(event.message or event.payload_summary or event.event_type),
                )
            )
    for span in spans:
        if span.status in FAILURE_STATUSES or span.status == "pending":
            evidence.append(
                DebugChatEvidenceRead(
                    source="runtime_span",
                    ref_id=span.span_id,
                    node_id=span.node_id,
                    status=span.status,
                    summary=_safe_text(_span_summary(span.attributes) or span.span_name),
                )
            )
    return evidence[:20]


def _build_findings(
    *,
    run: WorkflowRunRead,
    failed_node: DebugChatFailedNodeRead | None,
    evidence: list[DebugChatEvidenceRead],
) -> list[DebugChatFindingRead]:
    findings: list[DebugChatFindingRead] = []
    if failed_node is not None:
        findings.append(
            DebugChatFindingRead(
                title=_finding_title(failed_node.source),
                summary=_safe_text(
                    failed_node.error_message
                    or failed_node.error_type
                    or f"node status is {failed_node.status}"
                ),
                severity="error" if failed_node.status in FAILURE_STATUSES else "warning",
                source=failed_node.source,
                node_id=failed_node.node_id,
                evidence_ref=f"{failed_node.source}:{failed_node.node_id or run.run_id}",
            )
        )
    if run.status == "pending_approval":
        findings.append(
            DebugChatFindingRead(
                title="Run waits for approval",
                summary="The run is paused behind a human or tool approval gate.",
                severity="warning",
                source="workflow_run",
                node_id=failed_node.node_id if failed_node else "",
                evidence_ref=run.run_id,
            )
        )
    if not findings and evidence:
        findings.append(
            DebugChatFindingRead(
                title="No failed node located",
                summary="The selected run scope has sanitized evidence, but no failed node signal.",
                severity="info",
                source=evidence[0].source,
                node_id=evidence[0].node_id,
                evidence_ref=evidence[0].ref_id,
            )
        )
    return findings


def _build_recommended_actions(
    *,
    run: WorkflowRunRead,
    failed_node: DebugChatFailedNodeRead | None,
) -> list[DebugChatRecommendedActionRead]:
    actions = [
        DebugChatRecommendedActionRead(
            action_type="inspect",
            title="Open Run Observatory",
            summary=(
                "Inspect the sanitized timeline, runtime spans, events, and approval state "
                "before changing the workflow."
            ),
            target=run.run_id,
        )
    ]
    if failed_node is not None and failed_node.node_id:
        actions.append(
            DebugChatRecommendedActionRead(
                action_type="fix",
                title="Fix failed node inputs or policy",
                summary=(
                    f"Review node {failed_node.node_id} configuration, schema inputs, policy gate, "
                    "credential reference, and tool/template binding."
                ),
                target=failed_node.node_id,
            )
        )
    if run.status == "pending_approval":
        actions.append(
            DebugChatRecommendedActionRead(
                action_type="resume",
                title="Resume after approval",
                summary=(
                    "Approve or reject the pending gate from Run Observatory after checking "
                    "the policy context."
                ),
                target=run.run_id,
            )
        )
    if run.status in TERMINAL_STATUSES:
        actions.append(
            DebugChatRecommendedActionRead(
                action_type="retry",
                title="Retry after fixing failed node",
                summary=(
                    "After correcting the failed node or input, retry the terminal run from "
                    "Run Observatory."
                ),
                target=run.run_id,
                enabled=run.status != "success",
            )
        )
    if run.status in ACTIVE_STATUSES:
        actions.append(
            DebugChatRecommendedActionRead(
                action_type="wait",
                title="Wait for terminal state",
                summary="The run is still active. Continue observing events before retrying.",
                target=run.run_id,
                enabled=True,
            )
        )
    return actions


def _build_answer(
    *,
    run: WorkflowRunRead,
    failed_node: DebugChatFailedNodeRead | None,
) -> str:
    if failed_node is None:
        return (
            f"Run {run.run_id} is {run.status}. I could not locate a failed node from the "
            "sanitized checkpoints, runtime events, or runtime spans. Inspect Run Observatory "
            "for fresh events before retrying."
        )
    if failed_node.status == "pending_approval":
        return (
            f"Run {run.run_id} is waiting at node {failed_node.node_id}. The next safe step is "
            "to review the approval context in Run Observatory and resume only after the policy "
            "gate is satisfied."
        )
    return (
        f"Run {run.run_id} is {run.status}. The first failing signal is node "
        f"{failed_node.node_id or 'workflow'} ({failed_node.node_type}) from "
        f"{failed_node.source}: "
        f"{failed_node.error_message or failed_node.error_type or failed_node.status}. "
        "Fix the node input, policy, credential, or tool binding first, then retry from "
        "Run Observatory."
    )


def _span_summary(attributes: dict[str, Any]) -> str:
    values = []
    for key in SPAN_SUMMARY_KEYS:
        value = attributes.get(key)
        if value not in {"", None}:
            values.append(f"{key}={_safe_text(value, limit=220)}")
    return "; ".join(values)


def _summary_from_mapping(value: dict[str, Any]) -> str:
    summary = value.get("summary") or value.get("output_summary") or value.get("message")
    return _safe_text(summary)


def _node_type_from_span(span: Any) -> str:
    if span.span_kind == "tool":
        return "mcp_tool"
    if span.span_kind == "model":
        return "llm"
    return _safe_text(span.component or span.span_kind)


def _finding_title(source: str) -> str:
    return {
        "checkpoint": "Failed checkpoint",
        "runtime_event": "Failed runtime event",
        "runtime_span": "Failed runtime span",
        "workflow_run": "Failed workflow run",
    }.get(source, "Failed signal")


def _safe_text(value: object, *, limit: int = 500) -> str:
    if value is None:
        return ""
    redacted = redact_sensitive_text(str(value))
    if len(redacted) <= limit:
        return redacted
    return f"{redacted[: limit - 3]}..."
