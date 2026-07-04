import { parse, stringify } from "yaml";

import { analyzeWorkflowImport } from "./workflowDsl";
import type {
  EdgeDefinition,
  EdgeKind,
  NodeDefinition,
  NodeType,
  ProjectResourceCatalog,
  RiskLevel,
  WorkflowInputDefinition,
  WorkflowDefinition,
  WorkflowImportPreview,
  WorkflowStatus,
} from "./workflowTypes";

const NODE_TYPES: NodeType[] = [
  "start",
  "end",
  "agent",
  "llm",
  "mcp_tool",
  "shell",
  "http",
  "condition",
  "human_approval",
];
const RISK_LEVELS: RiskLevel[] = ["low", "medium", "high", "critical"];
const WORKFLOW_STATUSES: WorkflowStatus[] = ["draft", "published", "archived"];
const WORKFLOW_SCHEMA_VERSIONS = ["workflow.dsl/v0.1", "workflow.dsl/v0.2"] as const;
const EDGE_KINDS: EdgeKind[] = ["sequence", "condition", "parallel", "loop", "resume"];

export function parseWorkflowYaml(yamlText: string): WorkflowDefinition {
  const parsed = parse(yamlText);

  if (!isRecord(parsed)) {
    throw new Error("YAML 根节点必须是对象。");
  }

  return normalizeWorkflowDefinition(parsed);
}

export function exportWorkflowYaml(workflow: WorkflowDefinition): string {
  return stringify(toBackendWorkflowDocument(workflow), { lineWidth: 0 });
}

export function previewWorkflowImportFromYaml(
  yamlText: string,
  catalog: ProjectResourceCatalog,
  existingWorkflow?: WorkflowDefinition,
): WorkflowImportPreview {
  const workflow = parseWorkflowYaml(yamlText);

  return {
    workflow,
    analysis: analyzeWorkflowImport(workflow, catalog, existingWorkflow),
  };
}

function normalizeWorkflowDefinition(value: Record<string, unknown>): WorkflowDefinition {
  const schemaVersion = asEnum(value.schema_version, WORKFLOW_SCHEMA_VERSIONS, "schema_version");

  const workflow = value.workflow;
  if (!isRecord(workflow)) {
    throw new Error("workflow 元数据缺失。");
  }

  const workflowStatus = asEnum(workflow.status, WORKFLOW_STATUSES, "workflow.status");
  const nodes = value.nodes;
  const edges = value.edges;

  if (!Array.isArray(nodes) || nodes.length === 0) {
    throw new Error("nodes 必须是非空数组。");
  }

  if (!Array.isArray(edges)) {
    throw new Error("edges 必须是数组。");
  }

  return {
    schema_version: schemaVersion,
    workflow: {
      id: asRequiredString(workflow.id, "workflow.id"),
      project_id: asRequiredString(workflow.project_id, "workflow.project_id"),
      name: asRequiredString(workflow.name, "workflow.name"),
      version: asRequiredNumber(workflow.version, "workflow.version"),
      status: workflowStatus,
    },
    inputs: Array.isArray(value.inputs) ? value.inputs.map(normalizeInput) : undefined,
    nodes: nodes.map(normalizeNode),
    edges: edges.map(normalizeEdge),
    policies: isRecord(value.policies) ? { ...value.policies } : undefined,
  };
}

function normalizeInput(value: unknown): WorkflowInputDefinition {
  if (!isRecord(value)) {
    throw new Error("input 必须是对象。");
  }

  const inputType = asEnum(
    value.type,
    ["string", "number", "integer", "boolean", "object", "array"],
    "input.type",
  );

  return {
    key: asRequiredString(value.key ?? value.name, "input.key"),
    type: inputType,
    required: typeof value.required === "boolean" ? value.required : undefined,
    description: typeof value.description === "string" ? value.description : undefined,
  };
}

function toBackendWorkflowDocument(workflow: WorkflowDefinition): WorkflowDefinition {
  const document: WorkflowDefinition = {
    ...workflow,
    nodes: workflow.nodes.map((node) => ({
      ...node,
      data: sanitizeNodeDataForExport(node),
    })),
  };

  if (workflow.inputs) {
    document.inputs = workflow.inputs.map((input) => ({ ...input, key: input.key }));
  } else {
    delete document.inputs;
  }

  return document;
}

function sanitizeNodeDataForExport(node: NodeDefinition) {
  if (!isRecord(node.data)) {
    return node.data;
  }

  if (node.type !== "llm") {
    return node.data;
  }

  const data = { ...node.data };
  delete data.structured_output_placeholder;
  return data;
}

function normalizeNode(value: unknown): NodeDefinition {
  if (!isRecord(value)) {
    throw new Error("node 必须是对象。");
  }

  const nodeType = asEnum(value.type, NODE_TYPES, "node.type");
  const riskLevel = value.risk_level ? asEnum(value.risk_level, RISK_LEVELS, "node.risk_level") : undefined;
  const position = isRecord(value.position)
    ? {
        x: asRequiredNumber(value.position.x, "node.position.x"),
        y: asRequiredNumber(value.position.y, "node.position.y"),
      }
    : undefined;

  const normalized: NodeDefinition = {
    id: asRequiredString(value.id, "node.id"),
    type: nodeType,
    name: asRequiredString(value.name, "node.name"),
    description: typeof value.description === "string" ? value.description : undefined,
    risk_level: riskLevel,
    position,
    data: isRecord(value.data) ? { ...value.data } : undefined,
  };

  if (isRecord(value.parameters)) {
    normalized.parameters = { ...value.parameters };
  }
  if (Array.isArray(value.tool_group_refs)) {
    normalized.tool_group_refs = value.tool_group_refs.filter(
      (reference): reference is string => typeof reference === "string",
    );
  }
  if (isRecord(value.input_schema)) {
    normalized.input_schema = { ...value.input_schema };
  }
  if (isRecord(value.output_schema)) {
    normalized.output_schema = { ...value.output_schema };
  }
  if (isRecord(value.retry_policy)) {
    normalized.retry_policy = {
      max_attempts:
        typeof value.retry_policy.max_attempts === "number"
          ? value.retry_policy.max_attempts
          : undefined,
      backoff_seconds:
        typeof value.retry_policy.backoff_seconds === "number"
          ? value.retry_policy.backoff_seconds
          : undefined,
    };
  }
  if (typeof value.timeout_seconds === "number") {
    normalized.timeout_seconds = value.timeout_seconds;
  }
  if (typeof value.approval_policy_ref === "string") {
    normalized.approval_policy_ref = value.approval_policy_ref;
  }

  return normalized;
}

function normalizeEdge(value: unknown): EdgeDefinition {
  if (!isRecord(value)) {
    throw new Error("edge 必须是对象。");
  }

  const kind = value.kind ? asEnum(value.kind, EDGE_KINDS, "edge.kind") : "sequence";
  const edge: EdgeDefinition = {
    source: asRequiredString(value.source, "edge.source"),
    target: asRequiredString(value.target, "edge.target"),
    source_handle: typeof value.source_handle === "string" ? value.source_handle : null,
    target_handle: typeof value.target_handle === "string" ? value.target_handle : null,
    kind,
    label: typeof value.label === "string" ? value.label : undefined,
    condition: typeof value.condition === "string" ? value.condition : undefined,
  };

  if (kind === "loop") {
    if (!isRecord(value.loop)) {
      throw new Error("edge.loop 必须是对象。");
    }
    edge.loop = {
      max_iterations: asRequiredNumber(value.loop.max_iterations, "edge.loop.max_iterations"),
      while_expression:
        typeof value.loop.while_expression === "string" ? value.loop.while_expression : undefined,
      item_path: typeof value.loop.item_path === "string" ? value.loop.item_path : undefined,
    };
  }

  return edge;
}

function asRequiredString(value: unknown, fieldName: string) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${fieldName} 必须是非空字符串。`);
  }

  return value;
}

function asRequiredNumber(value: unknown, fieldName: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${fieldName} 必须是数字。`);
  }

  return value;
}

function asEnum<T extends string>(value: unknown, allowedValues: readonly T[], fieldName: string): T {
  if (typeof value !== "string" || !allowedValues.includes(value as T)) {
    throw new Error(`${fieldName} 不在允许范围内。`);
  }

  return value as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
