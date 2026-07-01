import { describe, expect, it } from "vitest";

import { SAMPLE_CATALOG, SAMPLE_WORKFLOW, SAMPLE_WORKFLOW_YAML } from "./sampleWorkflow";
import {
  buildImportPreviewSummary,
  flowToWorkflow,
  renameWorkflowNode,
  workflowToFlow,
} from "./workflowDsl";
import { previewWorkflowImportFromYaml } from "./workflowYaml";

describe("workflow DSL adapters", () => {
  it("maps workflow DSL nodes and edges to React Flow with stable ids", () => {
    const { analysis } = previewWorkflowImportFromYaml(SAMPLE_WORKFLOW_YAML, SAMPLE_CATALOG);
    const flow = workflowToFlow(SAMPLE_WORKFLOW, analysis);

    expect(flow.nodes.map((node) => node.id)).toEqual([
      "start_1",
      "agent_1",
      "tool_1",
      "shell_1",
      "end_1",
    ]);
    expect(flow.nodes[1].data.name).toBe("根因分析 Agent");
    expect(flow.nodes[1].data.nodeType).toBe("agent");
    expect(flow.nodes[3].data.resourceState).toBe("missing");
    expect(flow.edges[0].id).toBe("start_1->agent_1:default");
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

  it("builds an import preview summary from YAML and project resources", () => {
    const preview = previewWorkflowImportFromYaml(SAMPLE_WORKFLOW_YAML, SAMPLE_CATALOG);
    const summary = buildImportPreviewSummary(preview.analysis);

    expect(preview.workflow.workflow.name).toBe("运维排障导入样例");
    expect(summary.missingCount).toBe(1);
    expect(summary.missingLabels).toContain("shell_template: collect-pod-logs@1.0.0");
    expect(summary.riskLabels).toEqual(["medium", "high"]);
    expect(summary.canPublishOrRun).toBe(false);
  });
});
