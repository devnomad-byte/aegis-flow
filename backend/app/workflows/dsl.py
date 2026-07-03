import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal[
    "start",
    "end",
    "llm",
    "condition",
    "agent",
    "mcp_tool",
    "http",
    "shell",
    "human_approval",
]
RiskLevel = Literal["low", "medium", "high", "critical"]
WorkflowStatus = Literal["draft", "published", "archived"]
WorkflowInputType = Literal["string", "number", "integer", "boolean", "object", "array"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
STRICT_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")


class WorkflowMetadata(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    id: str
    name: str
    project_id: str
    version: int = Field(ge=1)
    status: WorkflowStatus = "draft"


class WorkflowInputDefinition(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    key: str
    type: WorkflowInputType
    required: bool = True
    description: str = ""


class AgentBudget(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    max_iterations: int = Field(default=6, ge=1, le=30)
    max_tool_calls: int = Field(default=5, ge=0, le=100)
    max_runtime_seconds: int = Field(default=300, ge=1, le=3600)


class AgentNodeData(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    goal: str
    tool_groups: list[str] = Field(default_factory=list)
    autonomy_level: Literal[0, 1, 2] = 0
    budget: AgentBudget = Field(default_factory=AgentBudget)


class LlmNodeData(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    model_policy_ref: str = Field(default="default", min_length=1, max_length=120)
    system_prompt: str = Field(min_length=1, max_length=20000)
    user_prompt: str = Field(min_length=1, max_length=20000)
    prompt_version: str = Field(default="v1", min_length=1, max_length=160)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    output_schema_ref: str = Field(default="", max_length=160)


class ConditionNodeData(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    expression: str
    cases: list[str]


class McpToolNodeData(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    mcp_server_ref: str
    tool_group_ref: str
    tool_name: str
    environment: str
    approval_required: bool = False


class HttpNodeData(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    action_ref: str
    method: HttpMethod
    url: str = Field(min_length=1, max_length=2048)
    tool_group_ref: str
    environment: str
    egress_profile_ref: str = Field(default="", max_length=120)
    headers_schema: dict[str, object] = Field(default_factory=dict)
    body_schema: dict[str, object] = Field(default_factory=dict)
    approval_required: bool = False


class ShellNodeData(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    template_ref: str
    template_version: int = Field(ge=1)
    environment: str
    approval_required: bool = True


class HumanApprovalNodeData(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    approval_policy_ref: str
    message_template: str


NodeData = Annotated[
    AgentNodeData
    | LlmNodeData
    | ConditionNodeData
    | McpToolNodeData
    | HttpNodeData
    | ShellNodeData
    | HumanApprovalNodeData
    | None,
    Field(default=None),
]


class NodePosition(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    x: float
    y: float


class NodeDefinition(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    id: str
    name: str
    type: NodeType
    data: NodeData = None
    position: NodePosition | None = None
    description: str = ""
    risk_level: RiskLevel = "low"

    @model_validator(mode="after")
    def validate_node_id_and_data(self) -> "NodeDefinition":
        if NODE_ID_PATTERN.fullmatch(self.id) is None:
            raise ValueError("node id must match [a-z][a-z0-9_]{2,63}")

        expected_data_type = {
            "agent": AgentNodeData,
            "llm": LlmNodeData,
            "condition": ConditionNodeData,
            "mcp_tool": McpToolNodeData,
            "http": HttpNodeData,
            "shell": ShellNodeData,
            "human_approval": HumanApprovalNodeData,
        }.get(self.type)
        if expected_data_type is not None and not isinstance(self.data, expected_data_type):
            raise ValueError(f"{self.type} node requires {expected_data_type.__name__}")
        return self


class EdgeDefinition(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


class WorkflowPolicies(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    default_environment: str = "test"
    max_runtime_seconds: int = Field(default=900, ge=1, le=86400)
    max_tool_calls: int = Field(default=20, ge=0, le=1000)


class PermissionImpact(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    tool_groups: list[str]
    mcp_servers: list[str]
    shell_templates: list[str]
    environments: list[str]
    risk_levels: list[RiskLevel]
    approval_required: bool


class TraceSpanPlan(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    node_id: str
    node_type: NodeType
    span_type: str


class WorkflowDefinition(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    schema_version: Literal["workflow.dsl/v0.1"] = "workflow.dsl/v0.1"
    workflow: WorkflowMetadata
    inputs: list[WorkflowInputDefinition] = Field(default_factory=list)
    nodes: list[NodeDefinition]
    edges: list[EdgeDefinition]
    policies: WorkflowPolicies = Field(default_factory=WorkflowPolicies)

    @model_validator(mode="after")
    def validate_graph(self) -> "WorkflowDefinition":
        nodes_by_id = {node.id: node for node in self.nodes}
        if len(nodes_by_id) != len(self.nodes):
            raise ValueError("duplicate node id")

        start_nodes = [node for node in self.nodes if node.type == "start"]
        if len(start_nodes) != 1:
            raise ValueError("workflow must contain exactly one start node")

        if not any(node.type == "end" for node in self.nodes):
            raise ValueError("workflow must contain at least one end node")

        for edge in self.edges:
            source = nodes_by_id.get(edge.source)
            target = nodes_by_id.get(edge.target)
            if source is None:
                raise ValueError(f"unknown source node: {edge.source}")
            if target is None:
                raise ValueError(f"unknown target node: {edge.target}")
            if target.type == "start":
                raise ValueError("edge cannot target start node")
            if source.type == "end":
                raise ValueError("edge cannot start from end node")
            if source.type == "condition":
                self._validate_condition_edge(source, edge)

        self._validate_reachability(start_nodes[0].id, nodes_by_id)
        return self

    def _validate_condition_edge(self, source: NodeDefinition, edge: EdgeDefinition) -> None:
        if not isinstance(source.data, ConditionNodeData):
            raise ValueError("condition node requires cases")
        allowed_handles = {f"case:{case}" for case in source.data.cases}
        if edge.source_handle not in allowed_handles:
            raise ValueError("condition edge handle must match declared cases")

    def _validate_reachability(self, start_id: str, nodes_by_id: dict[str, NodeDefinition]) -> None:
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes_by_id}
        for edge in self.edges:
            outgoing[edge.source].append(edge.target)

        reachable = {start_id}
        frontier = [start_id]
        while frontier:
            current = frontier.pop()
            for target in outgoing[current]:
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)

        for node_id in nodes_by_id:
            if node_id not in reachable:
                raise ValueError(f"unreachable node: {node_id}")

    def permission_impact(self) -> PermissionImpact:
        tool_groups: set[str] = set()
        mcp_servers: set[str] = set()
        shell_templates: set[str] = set()
        environments: set[str] = set()
        risk_levels: set[RiskLevel] = set()
        approval_required = False

        for node in self.nodes:
            if node.type not in {"start", "end", "condition"}:
                risk_levels.add(node.risk_level)
            if node.risk_level in {"high", "critical"}:
                approval_required = True
            if isinstance(node.data, AgentNodeData):
                tool_groups.update(node.data.tool_groups)
            elif isinstance(node.data, McpToolNodeData):
                tool_groups.add(node.data.tool_group_ref)
                mcp_servers.add(node.data.mcp_server_ref)
                environments.add(node.data.environment)
                approval_required = approval_required or node.data.approval_required
            elif isinstance(node.data, HttpNodeData):
                tool_groups.add(node.data.tool_group_ref)
                environments.add(node.data.environment)
                approval_required = approval_required or node.data.approval_required
            elif isinstance(node.data, ShellNodeData):
                shell_templates.add(f"{node.data.template_ref}@{node.data.template_version}")
                environments.add(node.data.environment)
                approval_required = approval_required or node.data.approval_required

        return PermissionImpact(
            tool_groups=sorted(tool_groups),
            mcp_servers=sorted(mcp_servers),
            shell_templates=sorted(shell_templates),
            environments=sorted(environments),
            risk_levels=sorted(risk_levels, key=["low", "medium", "high", "critical"].index),
            approval_required=approval_required,
        )

    def build_trace_span_plan(self) -> list[TraceSpanPlan]:
        spans: list[TraceSpanPlan] = []
        for node in self.nodes:
            spans.append(
                TraceSpanPlan(
                    node_id=node.id,
                    node_type=node.type,
                    span_type="workflow.node",
                )
            )
            if node.type == "agent":
                spans.append(
                    TraceSpanPlan(
                        node_id=node.id,
                        node_type=node.type,
                        span_type="agent.subgraph",
                    )
                )
            if node.type == "llm":
                spans.append(
                    TraceSpanPlan(
                        node_id=node.id,
                        node_type=node.type,
                        span_type="llm.model_call",
                    )
                )
        return spans
