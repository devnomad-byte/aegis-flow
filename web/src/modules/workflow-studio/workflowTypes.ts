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

export type WorkflowMetadata = {
  id: string;
  project_id: string;
  name: string;
  version: number;
  status: WorkflowStatus;
};

export type WorkflowInputDefinition = {
  name: string;
  type: "string" | "number" | "boolean" | "object" | "array";
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
  structured_output_placeholder?: string;
};

export type EdgeDefinition = {
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
};

export type WorkflowPolicies = {
  require_approval_for_risk?: RiskLevel[];
  max_runtime_seconds?: number;
  allowed_environments?: string[];
};

export type WorkflowDefinition = {
  schema_version: "workflow.dsl/v0.1";
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
  can_create_draft: boolean;
  can_publish_or_run: boolean;
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
};
