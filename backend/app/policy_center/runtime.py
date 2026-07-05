import time
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.app.policy_center.schemas import ApprovalPolicyRule, ApprovalPolicyVersionRead
from backend.app.policy_gate.schemas import (
    PolicyGateDecision,
    PolicyGateEventCreate,
    PolicyGateEventRead,
)
from backend.app.security.redaction import redact_sensitive_text
from backend.app.tool_registry.schemas import RiskLevel

ApprovalPolicyRuntimeTargetKind = Literal[
    "tool_invocation",
    "shell_execution",
    "model_invocation",
]


class PublishedApprovalPolicyStore(Protocol):
    async def load_published_approval_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
    ) -> ApprovalPolicyVersionRead | None:
        raise NotImplementedError


class PolicyGateEventWriter(Protocol):
    async def record_event(self, request: PolicyGateEventCreate) -> PolicyGateEventRead:
        raise NotImplementedError


class ApprovalPolicyDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    target_kind: ApprovalPolicyRuntimeTargetKind
    target_ref: str = Field(min_length=1, max_length=260)
    risk_level: RiskLevel
    policy_ref: str = Field(default="default", max_length=160)
    workflow_ref: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    tool_group_refs: list[str] = Field(default_factory=list)
    tool_ref: str = Field(default="", max_length=260)
    shell_template_ref: str = Field(default="", max_length=160)
    model_policy_ref: str = Field(default="", max_length=120)
    environment_key: str = Field(default="", max_length=80)
    default_approval_required: bool = False


class ApprovalPolicyDecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: PolicyGateDecision
    policy_ref: str
    policy_version: int | None = None
    rule_ref: str
    target_type: str
    target_ref: str
    risk_level: RiskLevel
    approval_required: bool
    reason_summary: str
    event_id: UUID | None = None


@dataclass(frozen=True)
class ApprovalPolicyRuntimeEvaluator:
    policy_store: PublishedApprovalPolicyStore
    policy_gate_store: PolicyGateEventWriter

    async def evaluate_and_record(
        self,
        request: ApprovalPolicyDecisionRequest,
    ) -> ApprovalPolicyDecisionResult:
        started = time.perf_counter()
        policy = await self.policy_store.load_published_approval_policy(
            project_id=request.project_id,
            policy_ref=request.policy_ref,
        )
        result = _evaluate_policy(request, policy)
        event = await self.policy_gate_store.record_event(
            PolicyGateEventCreate(
                project_id=request.project_id,
                actor_id=request.actor_id,
                event_ref=f"approval_policy:{request.target_kind}:{uuid4().hex}",
                gate_ref="approval_policy_runtime",
                policy_ref=result.policy_ref,
                rule_ref=result.rule_ref,
                target_type=result.target_type,
                target_ref=result.target_ref,
                workflow_ref=request.workflow_ref,
                run_id=request.run_id,
                node_id=request.node_id,
                trace_id=request.trace_id,
                decision=result.decision,
                risk_level=result.risk_level,
                approval_required=result.approval_required,
                reason_summary=result.reason_summary,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                created_by=request.actor_id,
                updated_by=request.actor_id,
            )
        )
        return result.model_copy(update={"event_id": event.id})


def _evaluate_policy(
    request: ApprovalPolicyDecisionRequest,
    policy: ApprovalPolicyVersionRead | None,
) -> ApprovalPolicyDecisionResult:
    if policy is not None:
        for rule in policy.rules:
            if _rule_matches_request(rule, request):
                return _decision_from_rule(request, policy, rule)

    if request.default_approval_required or request.risk_level in {"high", "critical"}:
        return ApprovalPolicyDecisionResult(
            decision="approval_required",
            policy_ref=policy.policy_ref if policy is not None else request.policy_ref,
            policy_version=policy.version if policy is not None else None,
            rule_ref="default_approval_floor",
            target_type=request.target_kind,
            target_ref=request.target_ref,
            risk_level=request.risk_level,
            approval_required=True,
            reason_summary="Default approval floor applies to this runtime action",
        )

    return ApprovalPolicyDecisionResult(
        decision="allowed",
        policy_ref=policy.policy_ref if policy is not None else request.policy_ref,
        policy_version=policy.version if policy is not None else None,
        rule_ref="default_allow",
        target_type=request.target_kind,
        target_ref=request.target_ref,
        risk_level=request.risk_level,
        approval_required=False,
        reason_summary="No approval policy rule matched; default allow applies",
    )


def _decision_from_rule(
    request: ApprovalPolicyDecisionRequest,
    policy: ApprovalPolicyVersionRead,
    rule: ApprovalPolicyRule,
) -> ApprovalPolicyDecisionResult:
    decision: PolicyGateDecision
    if rule.action == "deny":
        decision = "denied"
    elif rule.action == "require_approval":
        decision = "approval_required"
    else:
        decision = "allowed"

    if decision == "allowed" and request.risk_level in {"high", "critical"}:
        decision = "approval_required"

    approval_required = decision == "approval_required"
    reason = rule.reason or rule.title
    return ApprovalPolicyDecisionResult(
        decision=decision,
        policy_ref=policy.policy_ref,
        policy_version=policy.version,
        rule_ref=rule.rule_id,
        target_type=request.target_kind,
        target_ref=request.target_ref,
        risk_level=request.risk_level,
        approval_required=approval_required,
        reason_summary=redact_sensitive_text(reason)[:1000],
    )


def _rule_matches_request(
    rule: ApprovalPolicyRule,
    request: ApprovalPolicyDecisionRequest,
) -> bool:
    if rule.target_kind != request.target_kind:
        return False
    if request.risk_level not in set(rule.risk_levels):
        return False

    match = rule.match
    if match.environment_keys and request.environment_key not in set(match.environment_keys):
        return False
    if match.tool_group_refs and not set(match.tool_group_refs).intersection(
        request.tool_group_refs
    ):
        return False
    if match.tool_refs and request.tool_ref not in set(match.tool_refs):
        return False
    if match.shell_template_refs and request.shell_template_ref not in set(
        match.shell_template_refs
    ):
        return False
    return not (
        match.model_policy_refs and request.model_policy_ref not in set(match.model_policy_refs)
    )
