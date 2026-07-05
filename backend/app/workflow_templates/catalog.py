from uuid import UUID

from backend.app.workflow_templates.schemas import (
    InternalWorkflowTemplate,
    WorkflowTemplateDependencies,
    WorkflowTemplateRead,
)
from backend.app.workflows.dsl import (
    AgentBudget,
    AgentNodeData,
    ConditionNodeData,
    EdgeDefinition,
    HumanApprovalNodeData,
    LlmNodeData,
    McpToolNodeData,
    NodeDefinition,
    NodePosition,
    WorkflowDefinition,
    WorkflowInputDefinition,
    WorkflowMetadata,
    WorkflowPolicies,
)
from backend.app.workflows.yaml_io import ProjectResourceCatalog, analyze_workflow_import

TEMPLATE_PROJECT_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def list_workflow_templates(
    *,
    project_id: UUID,
    catalog: ProjectResourceCatalog,
) -> list[WorkflowTemplateRead]:
    return [
        _template_to_read(template, project_id=project_id, catalog=catalog)
        for template in _INTERNAL_TEMPLATES
    ]


def get_workflow_template(
    template_id: str,
    *,
    project_id: UUID,
    catalog: ProjectResourceCatalog,
) -> WorkflowTemplateRead | None:
    template = _find_template(template_id)
    if template is None:
        return None
    return _template_to_read(template, project_id=project_id, catalog=catalog)


def instantiate_template_workflow(
    template_id: str,
    *,
    project_id: UUID,
    workflow_name: str = "",
) -> WorkflowDefinition | None:
    template = _find_template(template_id)
    if template is None:
        return None

    name = workflow_name.strip() or template.workflow.workflow.name
    return template.workflow.model_copy(
        deep=True,
        update={
            "workflow": template.workflow.workflow.model_copy(
                update={
                    "name": name,
                    "project_id": str(project_id),
                    "version": 1,
                    "status": "draft",
                }
            )
        },
    )


def _find_template(template_id: str) -> InternalWorkflowTemplate | None:
    return next(
        (template for template in _INTERNAL_TEMPLATES if template.id == template_id),
        None,
    )


def _template_to_read(
    template: InternalWorkflowTemplate,
    *,
    project_id: UUID,
    catalog: ProjectResourceCatalog,
) -> WorkflowTemplateRead:
    workflow = instantiate_template_workflow(template.id, project_id=project_id)
    if workflow is None:
        raise ValueError(f"unknown workflow template: {template.id}")
    analysis = analyze_workflow_import(workflow, catalog=catalog)
    return WorkflowTemplateRead(
        id=template.id,
        name=template.name,
        category=template.category,
        summary=template.summary,
        persona=template.persona,
        difficulty=template.difficulty,
        estimated_setup_minutes=template.estimated_setup_minutes,
        recommended_for=template.recommended_for,
        dependencies=template.dependencies,
        risk_level=template.risk_level,
        approval_required=template.approval_required,
        node_count=len(template.workflow.nodes),
        analysis=analysis,
    )


def _workflow_metadata(workflow_id: str, name: str) -> WorkflowMetadata:
    return WorkflowMetadata(
        id=workflow_id,
        name=name,
        project_id=TEMPLATE_PROJECT_PLACEHOLDER,
        version=1,
        status="draft",
    )


_INTERNAL_TEMPLATES: tuple[InternalWorkflowTemplate, ...] = (
    InternalWorkflowTemplate(
        id="ops-incident-diagnosis",
        name="Ops Incident Diagnosis",
        category="ops",
        summary=(
            "Diagnose production incidents with governed read-only tools and approval recovery."
        ),
        persona="SRE / 运维负责人",
        difficulty="intermediate",
        estimated_setup_minutes=20,
        recommended_for=["502 diagnosis", "release rollback review", "service degradation triage"],
        dependencies=WorkflowTemplateDependencies(
            tool_groups=["k8s.readonly"],
            mcp_servers=["mcp-k8s-prod"],
            environments=["test", "prod"],
            approval_policies=["ops-change-approval"],
        ),
        risk_level="high",
        approval_required=True,
        workflow=WorkflowDefinition(
            schema_version="workflow.dsl/v0.2",
            workflow=_workflow_metadata("ops_incident_diagnosis", "Ops Incident Diagnosis"),
            inputs=[
                WorkflowInputDefinition(
                    key="incident_summary",
                    type="string",
                    required=True,
                    description="User supplied incident context.",
                )
            ],
            nodes=[
                NodeDefinition(
                    id="start_1",
                    name="Incident Intake",
                    type="start",
                    position=NodePosition(x=0, y=80),
                ),
                NodeDefinition(
                    id="classify_1",
                    name="Classify Incident",
                    type="llm",
                    risk_level="medium",
                    position=NodePosition(x=260, y=80),
                    data=LlmNodeData(
                        model_policy_ref="default",
                        system_prompt="You classify incident severity using only supplied context.",
                        user_prompt=(
                            "Incident: {{incident_summary}}\n"
                            "Return severity, suspected domain, and evidence to collect."
                        ),
                        output_schema={"type": "object"},
                    ),
                ),
                NodeDefinition(
                    id="agent_1",
                    name="Gather Read-only Evidence",
                    type="agent",
                    risk_level="medium",
                    position=NodePosition(x=540, y=80),
                    data=AgentNodeData(
                        goal="Collect pod, deployment, event, and recent rollout evidence.",
                        tool_groups=["k8s.readonly"],
                        autonomy_level=1,
                        budget=AgentBudget(
                            max_iterations=4,
                            max_tool_calls=6,
                            max_runtime_seconds=240,
                        ),
                    ),
                ),
                NodeDefinition(
                    id="tool_1",
                    name="Read Deployment Status",
                    type="mcp_tool",
                    risk_level="medium",
                    position=NodePosition(x=820, y=80),
                    data=McpToolNodeData(
                        mcp_server_ref="mcp-k8s-prod",
                        tool_group_ref="k8s.readonly",
                        tool_name="k8s.get_deployment_status",
                        environment="prod",
                    ),
                ),
                NodeDefinition(
                    id="approval_1",
                    name="Recovery Approval",
                    type="human_approval",
                    risk_level="high",
                    position=NodePosition(x=1100, y=80),
                    approval_policy_ref="ops-change-approval",
                    data=HumanApprovalNodeData(
                        approval_policy_ref="ops-change-approval",
                        message_template=(
                            "Approve proposed recovery action for {{incident_summary}}."
                        ),
                    ),
                ),
                NodeDefinition(
                    id="end_1",
                    name="Diagnosis Summary",
                    type="end",
                    position=NodePosition(x=1380, y=80),
                ),
            ],
            edges=[
                EdgeDefinition(source="start_1", target="classify_1"),
                EdgeDefinition(source="classify_1", target="agent_1"),
                EdgeDefinition(source="agent_1", target="tool_1"),
                EdgeDefinition(source="tool_1", target="approval_1"),
                EdgeDefinition(source="approval_1", target="end_1", kind="resume"),
            ],
            policies=WorkflowPolicies(
                default_environment="test",
                max_runtime_seconds=900,
                max_tool_calls=20,
            ),
        ),
    ),
    InternalWorkflowTemplate(
        id="support-complaint-triage",
        name="Support Complaint Triage",
        category="support",
        summary="Classify complaints, inspect customer context, and route VIP escalations.",
        persona="客服主管",
        difficulty="starter",
        estimated_setup_minutes=15,
        recommended_for=["complaint triage", "VIP escalation", "ticket drafting"],
        dependencies=WorkflowTemplateDependencies(
            tool_groups=["crm.readonly", "ticket.write"],
            mcp_servers=["mcp-crm-prod"],
            environments=["prod"],
            approval_policies=["customer-care-approval"],
        ),
        risk_level="medium",
        approval_required=True,
        workflow=WorkflowDefinition(
            schema_version="workflow.dsl/v0.2",
            workflow=_workflow_metadata("support_complaint_triage", "Support Complaint Triage"),
            inputs=[
                WorkflowInputDefinition(
                    key="complaint_text",
                    type="string",
                    required=True,
                    description="Customer complaint text.",
                )
            ],
            nodes=[
                NodeDefinition(id="start_1", name="Complaint Intake", type="start"),
                NodeDefinition(
                    id="classify_1",
                    name="Classify Complaint",
                    type="llm",
                    risk_level="medium",
                    data=LlmNodeData(
                        model_policy_ref="default",
                        system_prompt="Classify support complaints into actionable routing labels.",
                        user_prompt=(
                            "Complaint: {{complaint_text}}\n"
                            "Return category, sentiment, and urgency."
                        ),
                        output_schema={"type": "object"},
                    ),
                ),
                NodeDefinition(
                    id="condition_1",
                    name="VIP Or High Risk",
                    type="condition",
                    risk_level="low",
                    data=ConditionNodeData(
                        expression="urgency == 'high' or customer_tier == 'vip'",
                        cases=["yes", "no"],
                    ),
                ),
                NodeDefinition(
                    id="agent_1",
                    name="Customer Context Agent",
                    type="agent",
                    risk_level="medium",
                    data=AgentNodeData(
                        goal="Gather allowed CRM and order context for complaint handling.",
                        tool_groups=["crm.readonly"],
                        autonomy_level=1,
                    ),
                ),
                NodeDefinition(
                    id="approval_1",
                    name="Escalation Approval",
                    type="human_approval",
                    risk_level="medium",
                    approval_policy_ref="customer-care-approval",
                    data=HumanApprovalNodeData(
                        approval_policy_ref="customer-care-approval",
                        message_template="Approve escalation for complaint: {{complaint_text}}.",
                    ),
                ),
                NodeDefinition(id="end_1", name="Ticket Draft", type="end"),
            ],
            edges=[
                EdgeDefinition(source="start_1", target="classify_1"),
                EdgeDefinition(source="classify_1", target="condition_1"),
                EdgeDefinition(
                    source="condition_1",
                    target="approval_1",
                    kind="condition",
                    source_handle="case:yes",
                    label="Escalate",
                ),
                EdgeDefinition(
                    source="condition_1",
                    target="agent_1",
                    kind="condition",
                    source_handle="case:no",
                    label="Collect context",
                ),
                EdgeDefinition(source="agent_1", target="end_1"),
                EdgeDefinition(source="approval_1", target="end_1", kind="resume"),
            ],
        ),
    ),
    InternalWorkflowTemplate(
        id="internal-reporting",
        name="Internal Reporting Assistant",
        category="data",
        summary="Turn an internal report request into governed data retrieval and cited narrative.",
        persona="运营 / 数据分析",
        difficulty="starter",
        estimated_setup_minutes=18,
        recommended_for=[
            "weekly operations report",
            "ticket trend summary",
            "service health report",
        ],
        dependencies=WorkflowTemplateDependencies(
            tool_groups=["reporting.readonly"],
            mcp_servers=["mcp-reporting-prod"],
            environments=["prod"],
        ),
        risk_level="medium",
        approval_required=False,
        workflow=WorkflowDefinition(
            schema_version="workflow.dsl/v0.2",
            workflow=_workflow_metadata("internal_reporting", "Internal Reporting Assistant"),
            inputs=[
                WorkflowInputDefinition(
                    key="report_request",
                    type="string",
                    required=True,
                    description="Business question or report request.",
                )
            ],
            nodes=[
                NodeDefinition(id="start_1", name="Report Request", type="start"),
                NodeDefinition(
                    id="plan_1",
                    name="Structure Query Plan",
                    type="llm",
                    risk_level="medium",
                    data=LlmNodeData(
                        model_policy_ref="default",
                        system_prompt=(
                            "Transform business report requests into safe read-only query plans."
                        ),
                        user_prompt=(
                            "Report request: {{report_request}}\n"
                            "Return metrics, filters, and citations needed."
                        ),
                        output_schema={"type": "object"},
                    ),
                ),
                NodeDefinition(
                    id="tool_1",
                    name="Fetch Reporting Data",
                    type="mcp_tool",
                    risk_level="medium",
                    data=McpToolNodeData(
                        mcp_server_ref="mcp-reporting-prod",
                        tool_group_ref="reporting.readonly",
                        tool_name="reporting.query_metrics",
                        environment="prod",
                    ),
                ),
                NodeDefinition(
                    id="summary_1",
                    name="Generate Cited Summary",
                    type="llm",
                    risk_level="medium",
                    data=LlmNodeData(
                        model_policy_ref="default",
                        system_prompt="Write concise internal reports with source citations.",
                        user_prompt="Use retrieved metrics to answer: {{report_request}}",
                        output_schema={"type": "object"},
                    ),
                ),
                NodeDefinition(id="end_1", name="Report Output", type="end"),
            ],
            edges=[
                EdgeDefinition(source="start_1", target="plan_1"),
                EdgeDefinition(source="plan_1", target="tool_1"),
                EdgeDefinition(source="tool_1", target="summary_1"),
                EdgeDefinition(source="summary_1", target="end_1"),
            ],
        ),
    ),
)
