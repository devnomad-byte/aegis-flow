import { parse, stringify } from "yaml";

import { analyzeWorkflowImport } from "./workflowDsl";
import type {
  EdgeDefinition,
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
  "mcp_tool",
  "shell",
  "http",
  "condition",
  "human_approval",
];
const RISK_LEVELS: RiskLevel[] = ["low", "medium", "high", "critical"];
const WORKFLOW_STATUSES: WorkflowStatus[] = ["draft", "published", "archived"];

export function parseWorkflowYaml(yamlText: string): WorkflowDefinition {
  const parsed = parse(yamlText);

  if (!isRecord(parsed)) {
    throw new Error("YAML 根节点必须是对象。");
  }

  return normalizeWorkflowDefinition(parsed);
}

export function exportWorkflowYaml(workflow: WorkflowDefinition): string {
  return stringify(workflow, { lineWidth: 0 });
}

export function previewWorkflowImportFromYaml(
  yamlText: string,
  catalog: ProjectResourceCatalog,
): WorkflowImportPreview {
  const workflow = parseWorkflowYaml(yamlText);

  return {
    workflow,
    analysis: analyzeWorkflowImport(workflow, catalog),
  };
}

function normalizeWorkflowDefinition(value: Record<string, unknown>): WorkflowDefinition {
  if (value.schema_version !== "workflow.dsl/v0.1") {
    throw new Error("仅支持 workflow.dsl/v0.1。");
  }

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
    schema_version: "workflow.dsl/v0.1",
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
    ["string", "number", "boolean", "object", "array"],
    "input.type",
  );

  return {
    name: asRequiredString(value.name, "input.name"),
    type: inputType,
    required: typeof value.required === "boolean" ? value.required : undefined,
    description: typeof value.description === "string" ? value.description : undefined,
  };
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

  return {
    id: asRequiredString(value.id, "node.id"),
    type: nodeType,
    name: asRequiredString(value.name, "node.name"),
    description: typeof value.description === "string" ? value.description : undefined,
    risk_level: riskLevel,
    position,
    data: isRecord(value.data) ? { ...value.data } : undefined,
  };
}

function normalizeEdge(value: unknown): EdgeDefinition {
  if (!isRecord(value)) {
    throw new Error("edge 必须是对象。");
  }

  return {
    source: asRequiredString(value.source, "edge.source"),
    target: asRequiredString(value.target, "edge.target"),
    source_handle: typeof value.source_handle === "string" ? value.source_handle : null,
    target_handle: typeof value.target_handle === "string" ? value.target_handle : null,
  };
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

function asEnum<T extends string>(value: unknown, allowedValues: T[], fieldName: string): T {
  if (typeof value !== "string" || !allowedValues.includes(value as T)) {
    throw new Error(`${fieldName} 不在允许范围内。`);
  }

  return value as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
