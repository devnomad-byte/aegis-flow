import type { Edge, Node } from "@xyflow/react";

export type NodeType =
  | "start"
  | "end"
  | "agent"
  | "llm"
  | "mcp_tool"
  | "shell"
  | "http"
  | "condition"
  | "human_approval";

export type RiskLevel = "low" | "medium" | "high" | "critical";

export type ResourceState = "ready" | "missing" | "neutral";

export type WorkflowStatus = "draft" | "published" | "archived";
export type WorkflowSchemaVersion = "workflow.dsl/v0.1" | "workflow.dsl/v0.2";
export type EdgeKind = "sequence" | "condition" | "parallel" | "loop" | "resume";

export type WorkflowMetadata = {
  id: string;
  project_id: string;
  name: string;
  version: number;
  status: WorkflowStatus;
};

export type WorkflowInputDefinition = {
  key: string;
  type: "string" | "number" | "integer" | "boolean" | "object" | "array";
  required?: boolean;
  description?: string;
};

export type NodePosition = {
  x: number;
  y: number;
};

export type NodeDefinition = {
  id: string;
  type: NodeType;
  name: string;
  description?: string;
  risk_level?: RiskLevel;
  position?: NodePosition;
  data?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  tool_group_refs?: string[];
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  retry_policy?: {
    max_attempts?: number;
    backoff_seconds?: number;
  };
  timeout_seconds?: number;
  approval_policy_ref?: string;
};

export type LlmNodeData = {
  model_policy_ref?: string;
  prompt_template_ref?: string;
  system_prompt?: string;
  user_prompt?: string;
  prompt_version?: string;
  temperature?: number;
  max_tokens?: number;
  output_schema_ref?: string;
  output_schema?: Record<string, unknown>;
};

export type EdgeDefinition = {
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
  kind?: EdgeKind;
  label?: string;
  condition?: string;
  loop?: {
    max_iterations: number;
    while_expression?: string;
    item_path?: string;
  };
};

export type WorkflowPolicies = {
  default_environment?: string;
  max_tool_calls?: number;
  max_runtime_seconds?: number;
  require_approval_for_risk?: RiskLevel[];
  allowed_environments?: string[];
};

export type WorkflowDefinition = {
  schema_version: WorkflowSchemaVersion;
  workflow: WorkflowMetadata;
  inputs?: WorkflowInputDefinition[];
  nodes: NodeDefinition[];
  edges: EdgeDefinition[];
  policies?: WorkflowPolicies;
};

export type PermissionImpact = {
  tool_groups: string[];
  mcp_servers: string[];
  shell_templates: string[];
  environments: string[];
  risk_levels: RiskLevel[];
  approval_required: boolean;
};

export type MissingResourceReference = {
  reference_type: "tool_group" | "mcp_server" | "shell_template" | "environment";
  reference: string;
};

export type WorkflowImportAnalysis = {
  permission_impact: PermissionImpact;
  missing_references: MissingResourceReference[];
  import_diff: WorkflowImportDiff;
  can_create_draft: boolean;
  can_publish_or_run: boolean;
};

export type WorkflowImportDiff = {
  added_nodes: string[];
  modified_nodes: string[];
  removed_nodes: string[];
  added_edges: string[];
  removed_edges: string[];
  changed_tool_groups: string[];
  has_breaking_changes: boolean;
};

export type WorkflowImportPreview = {
  workflow: WorkflowDefinition;
  analysis: WorkflowImportAnalysis;
};

export type WorkflowCanvasNodeData = Record<string, unknown> & {
  nodeId: string;
  name: string;
  nodeType: NodeType;
  riskLevel: RiskLevel;
  description: string;
  resourceState: ResourceState;
  missingReferences: string[];
};

export type WorkflowFlowNode = Node<WorkflowCanvasNodeData, "workflowNode">;

export type WorkflowFlowEdge = Edge;

export type WorkflowFlowModel = {
  nodes: WorkflowFlowNode[];
  edges: WorkflowFlowEdge[];
};

export type ProjectResourceCatalog = {
  toolGroups: string[];
  mcpServers: string[];
  shellTemplates: string[];
  environments: string[];
};

export type ImportPreviewSummary = {
  missingCount: number;
  missingLabels: string[];
  riskLabels: RiskLevel[];
  approvalRequired: boolean;
  canCreateDraft: boolean;
  canPublishOrRun: boolean;
  toolGroups: string[];
  mcpServers: string[];
  shellTemplates: string[];
  environments: string[];
  diffLabels: string[];
};
