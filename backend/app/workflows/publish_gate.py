from backend.app.workflows.dsl import (
    HumanApprovalNodeData,
    WorkflowDefinition,
)
from backend.app.workflows.schemas import (
    WorkflowPublishGateReason,
    WorkflowPublishGateResult,
)
from backend.app.workflows.yaml_io import WorkflowImportAnalysis


def evaluate_workflow_publish_gate(
    workflow: WorkflowDefinition,
    analysis: WorkflowImportAnalysis,
) -> WorkflowPublishGateResult:
    """Evaluate static publish blockers for a validated workflow draft."""
    reasons: list[WorkflowPublishGateReason] = []
    reasons.extend(_missing_reference_reasons(analysis))
    reasons.extend(_approval_policy_reasons(workflow, analysis))

    return WorkflowPublishGateResult(
        can_publish=not any(reason.severity == "blocker" for reason in reasons),
        reasons=reasons,
    )


def _missing_reference_reasons(
    analysis: WorkflowImportAnalysis,
) -> list[WorkflowPublishGateReason]:
    return [
        WorkflowPublishGateReason(
            code="missing_reference",
            message=f"Missing {reference.reference_type}: {reference.reference}",
            severity="blocker",
            reference_type=reference.reference_type,
            reference=reference.reference,
        )
        for reference in analysis.missing_references
    ]


def _approval_policy_reasons(
    workflow: WorkflowDefinition,
    analysis: WorkflowImportAnalysis,
) -> list[WorkflowPublishGateReason]:
    if not analysis.permission_impact.approval_required:
        return []

    if _workflow_has_approval_policy_reference(workflow):
        return []

    return [
        WorkflowPublishGateReason(
            code="approval_policy_required",
            message="Workflow requires an approval policy reference before publish.",
            severity="blocker",
            reference_type="approval_policy",
            reference="workflow",
        )
    ]


def _workflow_has_approval_policy_reference(workflow: WorkflowDefinition) -> bool:
    for node in workflow.nodes:
        if node.approval_policy_ref.strip():
            return True
        if isinstance(node.data, HumanApprovalNodeData) and node.data.approval_policy_ref.strip():
            return True
    return False
