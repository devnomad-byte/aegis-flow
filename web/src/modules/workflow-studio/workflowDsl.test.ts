import { describe, expect, it } from "vitest";

import { SAMPLE_CATALOG, SAMPLE_WORKFLOW, SAMPLE_WORKFLOW_YAML } from "./sampleWorkflow";
import {
  buildImportPreviewSummary,
  createWorkflowEdge,
  createWorkflowNode,
  deleteWorkflowEdge,
  deleteWorkflowNode,
  flowToWorkflow,
  renameWorkflowNode,
  updateWorkflowEdge,
  updateWorkflowNodeData,
  workflowToFlow,
} from "./workflowDsl";
import { exportWorkflowYaml, previewWorkflowImportFromYaml } from "./workflowYaml";
import type { WorkflowDefinition } from "./workflowTypes";

const WORKFLOW_V2_YAML = `
schema_version: workflow.dsl/v0.2
workflow:
  id: wf_yaml_ops_triage
  project_id: ops-command
  name: 运维排障导入样例 v2
  version: 2
  status: draft
nodes:
  - id: start_1
    type: start
    name: 接收告警
    position:
      x: 72
      y: 180
  - id: router_1
    type: condition
    name: 风险路由
    position:
      x: 320
      y: 180
    data:
      expression: alert.severity
      cases:
        - collect
        - finish
  - id: tool_1
    type: mcp_tool
    name: 查询 Pod 状态
    risk_level: medium
    position:
      x: 610
      y: 80
    parameters:
      namespace: ops
      dry_run: true
    tool_group_refs:
      - incident.write
    input_schema:
      type: object
    output_schema:
      type: object
    retry_policy:
      max_attempts: 2
      backoff_seconds: 3
    timeout_seconds: 120
    data:
      mcp_server_ref: cluster-observability
      tool_group_ref: kubernetes-readonly
      tool_name: kubectl_get_pods
      environment: staging
  - id: llm_1
    type: llm
    name: 汇总闭环
    risk_level: medium
    position:
      x: 880
      y: 180
    data:
      model_policy_ref: default
      prompt_template_ref: incident-summary
      prompt_version: v2
  - id: end_1
    type: end
    name: 输出报告
    position:
      x: 1160
      y: 180
edges:
  - source: start_1
    target: router_1
    kind: sequence
  - source: router_1
    target: tool_1
    source_handle: case:collect
    kind: condition
  - source: tool_1
    target: llm_1
    kind: parallel
    label: evidence
  - source: llm_1
    target: router_1
    kind: loop
    label: refine
    loop:
      max_iterations: 3
      while_expression: needs_more_context
  - source: router_1
    target: end_1
    source_handle: case:finish
    kind: condition
`;

describe("workflow DSL adapters", () => {
  it("maps workflow DSL nodes and edges to React Flow with stable ids", () => {
    const { analysis } = previewWorkflowImportFromYaml(SAMPLE_WORKFLOW_YAML, SAMPLE_CATALOG);
    const flow = workflowToFlow(SAMPLE_WORKFLOW, analysis);

    expect(flow.nodes.map((node) => node.id)).toEqual([
      "start_1",
      "agent_1",
      "tool_1",
      "shell_1",
      "llm_1",
      "end_1",
    ]);
    expect(flow.nodes[1].data.name).toBe("根因分析 Agent");
    expect(flow.nodes[1].data.nodeType).toBe("agent");
    expect(flow.nodes[3].data.resourceState).toBe("missing");
    expect(flow.edges[0].id).toBe("start_1->agent_1:sequence:default");
  });

  it("keeps parallel edge kinds distinct for the same node pair", () => {
    const workflow: WorkflowDefinition = {
      ...SAMPLE_WORKFLOW,
      schema_version: "workflow.dsl/v0.2",
      nodes: SAMPLE_WORKFLOW.nodes.filter((node) =>
        ["start_1", "agent_1", "end_1"].includes(node.id),
      ),
      edges: [
        {
          source: "agent_1",
          target: "end_1",
          kind: "sequence",
        },
        {
          source: "agent_1",
          target: "end_1",
          kind: "loop",
          label: "retry",
          loop: {
            max_iterations: 2,
          },
        },
      ],
    };

    const flow = workflowToFlow(workflow);
    const converted = flowToWorkflow(workflow, flow.nodes, flow.edges);

    expect(flow.edges.map((edge) => edge.id)).toEqual([
      "agent_1->end_1:sequence:default",
      "agent_1->end_1:loop:default",
    ]);
    expect(converted.edges.map((edge) => edge.kind)).toEqual(["sequence", "loop"]);
    expect(converted.edges.find((edge) => edge.kind === "loop")?.loop?.max_iterations).toBe(2);
  });

  it("renames a node without changing the stable node id", () => {
    const renamed = renameWorkflowNode(SAMPLE_WORKFLOW, "tool_1", "查看 Pod 事件");

    expect(renamed.nodes.find((node) => node.id === "tool_1")?.name).toBe("查看 Pod 事件");
    expect(renamed.edges.some((edge) => edge.source === "tool_1" || edge.target === "tool_1")).toBe(true);
  });

  it("converts React Flow changes back to workflow DSL", () => {
    const flow = workflowToFlow(SAMPLE_WORKFLOW);
    const renamedNodes = flow.nodes.map((node) =>
      node.id === "agent_1"
        ? {
            ...node,
            data: {
              ...node.data,
              name: "SRE 分析助手",
            },
          }
        : node,
    );

    const workflow = flowToWorkflow(SAMPLE_WORKFLOW, renamedNodes, flow.edges);

    expect(workflow.nodes.find((node) => node.id === "agent_1")?.id).toBe("agent_1");
    expect(workflow.nodes.find((node) => node.id === "agent_1")?.name).toBe("SRE 分析助手");
  });

  it("updates LLM node data without changing other nodes", () => {
    const workflow = updateWorkflowNodeData(SAMPLE_WORKFLOW, "llm_1", {
      model_policy_ref: "prod-fast",
      prompt_version: "incident-summary/v2",
      max_tokens: 256,
    });

    const llmNode = workflow.nodes.find((node) => node.id === "llm_1");
    expect(llmNode?.data?.model_policy_ref).toBe("prod-fast");
    expect(llmNode?.data?.prompt_version).toBe("incident-summary/v2");
    expect(llmNode?.data?.max_tokens).toBe(256);
    expect(workflow.nodes.find((node) => node.id === "agent_1")?.id).toBe("agent_1");
  });

  it("builds an import preview summary from YAML and project resources", () => {
    const preview = previewWorkflowImportFromYaml(SAMPLE_WORKFLOW_YAML, SAMPLE_CATALOG);
    const summary = buildImportPreviewSummary(preview.analysis);

    expect(preview.workflow.workflow.name).toBe("运维排障导入样例");
    expect(preview.workflow.inputs?.[0]?.key).toBe("alert_payload");
    expect(summary.missingCount).toBe(1);
    expect(summary.missingLabels).toContain("shell_template: collect-pod-logs@1");
    expect(summary.riskLabels).toEqual(["medium", "high"]);
    expect(summary.canPublishOrRun).toBe(false);
  });

  it("exports backend-compatible YAML keys and omits frontend-only draft fields", () => {
    const exportedYaml = exportWorkflowYaml(SAMPLE_WORKFLOW);

    expect(exportedYaml).toContain("key: alert_payload");
    expect(exportedYaml).not.toContain("name: alert_payload");
    expect(exportedYaml).not.toContain("structured_output_placeholder");
    expect(exportedYaml).toContain("template_version: 1");
  });

  it("parses workflow DSL v2 and reports import diff against the current canvas", () => {
    const preview = previewWorkflowImportFromYaml(
      WORKFLOW_V2_YAML,
      SAMPLE_CATALOG,
      SAMPLE_WORKFLOW,
    );
    const summary = buildImportPreviewSummary(preview.analysis);

    expect(preview.workflow.schema_version).toBe("workflow.dsl/v0.2");
    expect(preview.workflow.nodes.find((node) => node.id === "tool_1")?.parameters).toEqual({
      namespace: "ops",
      dry_run: true,
    });
    expect(preview.workflow.nodes.find((node) => node.id === "tool_1")?.tool_group_refs).toEqual([
      "incident.write",
    ]);
    expect(preview.workflow.edges.map((edge) => edge.kind)).toEqual([
      "sequence",
      "condition",
      "parallel",
      "loop",
      "condition",
    ]);
    expect(summary.diffLabels).toContain("added node: router_1");
    expect(summary.diffLabels).toContain("removed node: agent_1");
    expect(summary.diffLabels).toContain("changed tool group: incident.write");
    expect(summary.missingLabels).toContain("tool_group: incident.write");
  });

  it("preserves edge metadata and layout when converting React Flow changes back to DSL", () => {
    const workflow = previewWorkflowImportFromYaml(WORKFLOW_V2_YAML, SAMPLE_CATALOG).workflow;
    const flow = workflowToFlow(workflow);
    const movedNodes = flow.nodes.map((node) =>
      node.id === "tool_1"
        ? {
            ...node,
            position: { x: 700, y: 140 },
          }
        : node,
    );

    const converted = flowToWorkflow(workflow, movedNodes, flow.edges) as WorkflowDefinition;
    const loopEdge = converted.edges.find((edge) => edge.kind === "loop");

    expect(converted.nodes.find((node) => node.id === "tool_1")?.position).toEqual({
      x: 700,
      y: 140,
    });
    expect(loopEdge?.label).toBe("refine");
    expect(loopEdge?.loop?.max_iterations).toBe(3);
  });

  it("creates library nodes, edits loop edges, and deletes dependent edges in v2 DSL", () => {
    const withCondition = createWorkflowNode(SAMPLE_WORKFLOW, "condition");
    const condition = withCondition.nodes.at(-1);

    expect(withCondition.schema_version).toBe("workflow.dsl/v0.2");
    expect(condition?.type).toBe("condition");
    expect(condition?.id).toMatch(/^condition_\d+$/);
    expect(condition?.data).toEqual({ expression: "inputs.route", cases: ["default"] });

    const withLoop = createWorkflowEdge(withCondition, {
      source: "llm_1",
      target: condition?.id ?? "",
      kind: "loop",
    });
    const loopEdge = withLoop.edges.find((edge) => edge.kind === "loop");

    expect(loopEdge?.loop).toEqual({ max_iterations: 3 });

    const updated = updateWorkflowEdge(withLoop, "llm_1->condition_1:loop:default", {
      label: "refine",
      loop: { max_iterations: 5, while_expression: "needs_more_context" },
    });
    const updatedLoopEdge = updated.edges.find((edge) => edge.kind === "loop");

    expect(updatedLoopEdge?.label).toBe("refine");
    expect(updatedLoopEdge?.loop?.max_iterations).toBe(5);
    expect(updatedLoopEdge?.loop?.while_expression).toBe("needs_more_context");

    const withoutLoop = deleteWorkflowEdge(updated, "llm_1->condition_1:loop:default");

    expect(withoutLoop.edges.some((edge) => edge.kind === "loop")).toBe(false);

    const withoutCondition = deleteWorkflowNode(withLoop, condition?.id ?? "");

    expect(withoutCondition.nodes.some((node) => node.id === condition?.id)).toBe(false);
    expect(withoutCondition.edges.some((edge) => edge.target === condition?.id)).toBe(false);
  });
});
