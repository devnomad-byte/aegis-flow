import type {
  EdgeDefinition,
  ImportPreviewSummary,
  LlmNodeData,
  MissingResourceReference,
  NodeDefinition,
  ProjectResourceCatalog,
  RiskLevel,
  WorkflowDefinition,
  WorkflowFlowEdge,
  WorkflowFlowModel,
  WorkflowFlowNode,
  WorkflowImportAnalysis,
  WorkflowImportDiff,
} from "./workflowTypes";

const DEFAULT_RISK_LEVEL: RiskLevel = "low";
const APPROVAL_RISK_LEVELS: RiskLevel[] = ["high", "critical"];

export function workflowToFlow(
  workflow: WorkflowDefinition,
  analysis?: WorkflowImportAnalysis,
): WorkflowFlowModel {
  return {
    nodes: workflow.nodes.map((node, index) => ({
      id: node.id,
      type: "workflowNode",
      position: node.position ?? buildFallbackPosition(index),
      data: {
        nodeId: node.id,
        name: node.name,
        nodeType: node.type,
        riskLevel: node.risk_level ?? DEFAULT_RISK_LEVEL,
        description: node.description ?? "",
        resourceState: getNodeResourceState(node, analysis),
        missingReferences: getMissingReferencesForNode(node, analysis),
      },
    })),
    edges: workflow.edges.map(toFlowEdge),
  };
}

export function flowToWorkflow(
  workflow: WorkflowDefinition,
  nodes: WorkflowFlowNode[],
  edges: WorkflowFlowEdge[],
): WorkflowDefinition {
  const flowNodesById = new Map(nodes.map((node) => [node.id, node]));
  const existingEdgesById = new Map(
    workflow.edges.map((edge) => [buildEdgeIdentity(edge), edge]),
  );
  const existingEdgesByLooseIdentity = new Map(
    workflow.edges.map((edge) => [buildLooseEdgeIdentity(edge), edge]),
  );

  return {
    ...workflow,
    nodes: workflow.nodes.map((node) => {
      const flowNode = flowNodesById.get(node.id);

      if (!flowNode) {
        return node;
      }

      return {
        ...node,
        name: String(flowNode.data.name),
        position: {
          x: flowNode.position.x,
          y: flowNode.position.y,
        },
      };
    }),
    edges: edges.map((edge) => {
      const looseIdentity = buildLooseEdgeIdentity({
        source: edge.source,
        target: edge.target,
        source_handle: edge.sourceHandle ?? null,
        target_handle: edge.targetHandle ?? null,
      });
      const existingEdge =
        existingEdgesById.get(edge.id) ?? existingEdgesByLooseIdentity.get(looseIdentity);

      return {
        ...(existingEdge ?? {}),
        source: edge.source,
        target: edge.target,
        source_handle: edge.sourceHandle ?? null,
        target_handle: edge.targetHandle ?? null,
      };
    }),
  };
}

export function renameWorkflowNode(
  workflow: WorkflowDefinition,
  nodeId: string,
  name: string,
): WorkflowDefinition {
  return {
    ...workflow,
    nodes: workflow.nodes.map((node) => (node.id === nodeId ? { ...node, name } : node)),
  };
}

export function updateWorkflowNodeData(
  workflow: WorkflowDefinition,
  nodeId: string,
  dataPatch: Record<string, unknown>,
): WorkflowDefinition {
  return {
    ...workflow,
    nodes: workflow.nodes.map((node) =>
      node.id === nodeId
        ? {
            ...node,
            data: {
              ...(node.data ?? {}),
              ...dataPatch,
            },
          }
        : node,
    ),
  };
}

export function getLlmNodeData(node: NodeDefinition): LlmNodeData {
  if (node.type !== "llm") {
    return {};
  }

  return {
    model_policy_ref: asOptionalString(node.data?.model_policy_ref) ?? "default",
    prompt_template_ref: asOptionalString(node.data?.prompt_template_ref) ?? "",
    system_prompt: asOptionalString(node.data?.system_prompt) ?? "",
    user_prompt: asOptionalString(node.data?.user_prompt) ?? "",
    prompt_version: asOptionalString(node.data?.prompt_version) ?? "",
    temperature: asNumber(node.data?.temperature),
    max_tokens: asNumber(node.data?.max_tokens),
    output_schema_ref: asOptionalString(node.data?.output_schema_ref) ?? "",
    structured_output_placeholder:
      asOptionalString(node.data?.structured_output_placeholder) ?? "",
  };
}

export function analyzeWorkflowImport(
  workflow: WorkflowDefinition,
  catalog: ProjectResourceCatalog,
  existingWorkflow?: WorkflowDefinition,
): WorkflowImportAnalysis {
  const toolGroups = new Set<string>();
  const mcpServers = new Set<string>();
  const shellTemplates = new Set<string>();
  const environments = new Set<string>();
  const riskLevels = new Set<RiskLevel>();
  const missingReferences: MissingResourceReference[] = [];

  workflow.nodes.forEach((node) => {
    const riskLevel = node.risk_level;
    if (riskLevel) {
      riskLevels.add(riskLevel);
    }

    collectStringArray(node.tool_group_refs).forEach((toolGroup) => {
      toolGroups.add(toolGroup);
      addMissing(missingReferences, "tool_group", toolGroup, catalog.toolGroups);
    });

    collectStringArray(node.data?.tool_groups).forEach((toolGroup) => {
      toolGroups.add(toolGroup);
      addMissing(missingReferences, "tool_group", toolGroup, catalog.toolGroups);
    });

    collectStringArray(node.data?.mcp_servers).forEach((mcpServer) => {
      mcpServers.add(mcpServer);
      addMissing(missingReferences, "mcp_server", mcpServer, catalog.mcpServers);
    });

    const toolGroupRef = asString(node.data?.tool_group_ref);
    if (toolGroupRef) {
      toolGroups.add(toolGroupRef);
      addMissing(missingReferences, "tool_group", toolGroupRef, catalog.toolGroups);
    }

    const mcpServerRef = asString(node.data?.mcp_server_ref);
    if (mcpServerRef) {
      mcpServers.add(mcpServerRef);
      addMissing(missingReferences, "mcp_server", mcpServerRef, catalog.mcpServers);
    }

    const shellTemplate = buildShellTemplateReference(node);
    if (shellTemplate) {
      shellTemplates.add(shellTemplate);
      addMissing(missingReferences, "shell_template", shellTemplate, catalog.shellTemplates);
    }

    const environment = asString(node.data?.environment);
    if (environment) {
      environments.add(environment);
      addMissing(missingReferences, "environment", environment, catalog.environments);
    }
  });

  const riskList = sortRiskLevels([...riskLevels]);
  const approvalRequired = riskList.some((riskLevel) => APPROVAL_RISK_LEVELS.includes(riskLevel));
  const canPublishOrRun = missingReferences.length === 0 && !approvalRequired;

  return {
    permission_impact: {
      tool_groups: [...toolGroups].sort(),
      mcp_servers: [...mcpServers].sort(),
      shell_templates: [...shellTemplates].sort(),
      environments: [...environments].sort(),
      risk_levels: riskList,
      approval_required: approvalRequired,
    },
    missing_references: missingReferences,
    import_diff: buildWorkflowImportDiff(workflow, existingWorkflow),
    can_create_draft: true,
    can_publish_or_run: canPublishOrRun,
  };
}

export function buildImportPreviewSummary(analysis: WorkflowImportAnalysis): ImportPreviewSummary {
  return {
    missingCount: analysis.missing_references.length,
    missingLabels: analysis.missing_references.map(
      (reference) => `${reference.reference_type}: ${reference.reference}`,
    ),
    riskLabels: analysis.permission_impact.risk_levels,
    approvalRequired: analysis.permission_impact.approval_required,
    canCreateDraft: analysis.can_create_draft,
    canPublishOrRun: analysis.can_publish_or_run,
    toolGroups: analysis.permission_impact.tool_groups,
    mcpServers: analysis.permission_impact.mcp_servers,
    shellTemplates: analysis.permission_impact.shell_templates,
    environments: analysis.permission_impact.environments,
    diffLabels: buildDiffLabels(analysis.import_diff),
  };
}

function toFlowEdge(edge: EdgeDefinition): WorkflowFlowEdge {
  const kind = edge.kind ?? "sequence";
  const label = edge.label ?? (kind === "sequence" ? undefined : kind);

  return {
    id: buildEdgeIdentity(edge),
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_handle ?? undefined,
    targetHandle: edge.target_handle ?? undefined,
    animated: kind !== "sequence",
    label,
  };
}

function buildFallbackPosition(index: number) {
  return {
    x: 80 + (index % 3) * 280,
    y: 80 + Math.floor(index / 3) * 190,
  };
}

function getNodeResourceState(node: NodeDefinition, analysis?: WorkflowImportAnalysis) {
  if (!requiresProjectResource(node)) {
    return "neutral";
  }

  return getMissingReferencesForNode(node, analysis).length > 0 ? "missing" : "ready";
}

function getMissingReferencesForNode(node: NodeDefinition, analysis?: WorkflowImportAnalysis) {
  if (!analysis) {
    return [];
  }

  const nodeReferences = collectNodeReferences(node);
  return analysis.missing_references
    .filter((missing) => nodeReferences.has(`${missing.reference_type}:${missing.reference}`))
    .map((missing) => `${missing.reference_type}: ${missing.reference}`);
}

function requiresProjectResource(node: NodeDefinition) {
  return (
    node.type === "agent" ||
    node.type === "llm" ||
    node.type === "mcp_tool" ||
    node.type === "shell" ||
    node.type === "http"
  );
}

function collectNodeReferences(node: NodeDefinition) {
  const references = new Set<string>();

  collectStringArray(node.tool_group_refs).forEach((toolGroup) => {
    references.add(`tool_group:${toolGroup}`);
  });

  collectStringArray(node.data?.tool_groups).forEach((toolGroup) => {
    references.add(`tool_group:${toolGroup}`);
  });

  collectStringArray(node.data?.mcp_servers).forEach((mcpServer) => {
    references.add(`mcp_server:${mcpServer}`);
  });

  const toolGroupRef = asString(node.data?.tool_group_ref);
  if (toolGroupRef) {
    references.add(`tool_group:${toolGroupRef}`);
  }

  const mcpServerRef = asString(node.data?.mcp_server_ref);
  if (mcpServerRef) {
    references.add(`mcp_server:${mcpServerRef}`);
  }

  const shellTemplate = buildShellTemplateReference(node);
  if (shellTemplate) {
    references.add(`shell_template:${shellTemplate}`);
  }

  const environment = asString(node.data?.environment);
  if (environment) {
    references.add(`environment:${environment}`);
  }

  return references;
}

function asNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asOptionalString(value: unknown) {
  return typeof value === "string" ? value : null;
}

function addMissing(
  missingReferences: MissingResourceReference[],
  reference_type: MissingResourceReference["reference_type"],
  reference: string,
  availableReferences: string[],
) {
  if (availableReferences.includes(reference)) {
    return;
  }

  if (
    missingReferences.some(
      (missing) => missing.reference_type === reference_type && missing.reference === reference,
    )
  ) {
    return;
  }

  missingReferences.push({ reference_type, reference });
}

function buildShellTemplateReference(node: NodeDefinition) {
  const templateRef = asString(node.data?.template_ref);

  if (!templateRef) {
    return null;
  }

  const templateVersion = asString(node.data?.template_version);
  return templateVersion ? `${templateRef}@${templateVersion}` : templateRef;
}

function collectStringArray(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function asString(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function sortRiskLevels(riskLevels: RiskLevel[]) {
  const order: Record<RiskLevel, number> = {
    low: 0,
    medium: 1,
    high: 2,
    critical: 3,
  };

  return riskLevels.sort((left, right) => order[left] - order[right]);
}

function buildWorkflowImportDiff(
  workflow: WorkflowDefinition,
  existingWorkflow?: WorkflowDefinition,
): WorkflowImportDiff {
  if (!existingWorkflow) {
    return {
      added_nodes: workflow.nodes.map((node) => node.id).sort(),
      modified_nodes: [],
      removed_nodes: [],
      added_edges: workflow.edges.map(buildEdgeIdentity).sort(),
      removed_edges: [],
      changed_tool_groups: collectWorkflowToolGroups(workflow),
      has_breaking_changes: false,
    };
  }

  const oldNodes = new Map(existingWorkflow.nodes.map((node) => [node.id, node]));
  const newNodes = new Map(workflow.nodes.map((node) => [node.id, node]));
  const oldNodeIds = new Set(oldNodes.keys());
  const newNodeIds = new Set(newNodes.keys());
  const oldEdges = new Set(existingWorkflow.edges.map(buildEdgeIdentity));
  const newEdges = new Set(workflow.edges.map(buildEdgeIdentity));
  const oldToolGroups = new Set(collectWorkflowToolGroups(existingWorkflow));
  const newToolGroups = new Set(collectWorkflowToolGroups(workflow));

  const addedNodes = [...newNodeIds].filter((nodeId) => !oldNodeIds.has(nodeId)).sort();
  const removedNodes = [...oldNodeIds].filter((nodeId) => !newNodeIds.has(nodeId)).sort();
  const modifiedNodes = [...newNodeIds]
    .filter((nodeId) => oldNodes.has(nodeId))
    .filter((nodeId) => JSON.stringify(newNodes.get(nodeId)) !== JSON.stringify(oldNodes.get(nodeId)))
    .sort();

  return {
    added_nodes: addedNodes,
    modified_nodes: modifiedNodes,
    removed_nodes: removedNodes,
    added_edges: [...newEdges].filter((edgeId) => !oldEdges.has(edgeId)).sort(),
    removed_edges: [...oldEdges].filter((edgeId) => !newEdges.has(edgeId)).sort(),
    changed_tool_groups: [...newToolGroups]
      .filter((toolGroup) => !oldToolGroups.has(toolGroup))
      .sort(),
    has_breaking_changes: removedNodes.length > 0 || [...oldEdges].some((edgeId) => !newEdges.has(edgeId)),
  };
}

function collectWorkflowToolGroups(workflow: WorkflowDefinition) {
  const toolGroups = new Set<string>();

  workflow.nodes.forEach((node) => {
    collectStringArray(node.tool_group_refs).forEach((toolGroup) => toolGroups.add(toolGroup));
    collectStringArray(node.data?.tool_groups).forEach((toolGroup) => toolGroups.add(toolGroup));
    const toolGroupRef = asString(node.data?.tool_group_ref);
    if (toolGroupRef) {
      toolGroups.add(toolGroupRef);
    }
  });

  return [...toolGroups].sort();
}

function buildDiffLabels(diff: WorkflowImportDiff) {
  return [
    ...diff.added_nodes.map((nodeId) => `added node: ${nodeId}`),
    ...diff.modified_nodes.map((nodeId) => `modified node: ${nodeId}`),
    ...diff.removed_nodes.map((nodeId) => `removed node: ${nodeId}`),
    ...diff.added_edges.map((edgeId) => `added edge: ${edgeId}`),
    ...diff.removed_edges.map((edgeId) => `removed edge: ${edgeId}`),
    ...diff.changed_tool_groups.map((toolGroup) => `changed tool group: ${toolGroup}`),
  ];
}

function buildEdgeIdentity(edge: Pick<EdgeDefinition, "source" | "target" | "source_handle" | "target_handle" | "kind">) {
  const kind = edge.kind ?? "sequence";
  const sourceHandle = edge.source_handle ?? "default";
  const targetHandle = edge.target_handle ? `:${edge.target_handle}` : "";
  return `${edge.source}->${edge.target}:${kind}:${sourceHandle}${targetHandle}`;
}

function buildLooseEdgeIdentity(edge: Pick<EdgeDefinition, "source" | "target" | "source_handle" | "target_handle">) {
  const sourceHandle = edge.source_handle ?? "default";
  const targetHandle = edge.target_handle ? `:${edge.target_handle}` : "";
  return `${edge.source}->${edge.target}:${sourceHandle}${targetHandle}`;
}
