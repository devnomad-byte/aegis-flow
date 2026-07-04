import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { WorkflowStudio } from "./WorkflowStudio";
import { defaultProjectContext } from "../../shell/projectContext";

describe("WorkflowStudio", () => {
  it("previews imported YAML, applies it to the canvas, renames a node, and exports YAML", async () => {
    const user = userEvent.setup();

    render(<WorkflowStudio project={defaultProjectContext} />);

    expect(screen.getByText("Workflow Canvas")).toBeInTheDocument();
    expect(screen.getByText("根因分析 Agent")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "预览导入" }));

    expect(screen.getByText("缺失资源 1")).toBeInTheDocument();
    expect(screen.getByText("shell_template: collect-pod-logs@1")).toBeInTheDocument();
    expect(screen.getByText("禁止发布/运行")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "应用预览到画布" }));

    const nodeName = screen.getByLabelText("节点名称");
    await user.clear(nodeName);
    await user.type(nodeName, "SRE 分析助手");

    expect(screen.getByText("SRE 分析助手")).toBeInTheDocument();
    expect(screen.getAllByText("agent_1").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "导出 YAML" }));

    const exportedYaml = screen.getByLabelText("导出的 Workflow YAML") as HTMLTextAreaElement;
    expect(exportedYaml.value).toContain("id: agent_1");
    expect(exportedYaml.value).toContain("name: SRE 分析助手");
  });

  it("edits LLM node controls and shows model usage in the trace timeline", async () => {
    const user = userEvent.setup();

    render(<WorkflowStudio project={defaultProjectContext} />);

    const nodeName = await screen.findByLabelText(/节点名称|鑺傜偣鍚嶇О/);
    await user.clear(nodeName);
    await user.type(nodeName, "LLM Summary");

    expect(screen.getByText("LLM Controls")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Model Policy Ref"));
    await user.type(screen.getByLabelText("Model Policy Ref"), "prod-fast");
    await user.clear(screen.getByLabelText("Prompt Template Ref"));
    await user.type(screen.getByLabelText("Prompt Template Ref"), "incident-summary");
    await user.clear(screen.getByLabelText("Prompt Version"));
    await user.type(screen.getByLabelText("Prompt Version"), "v2");
    await user.clear(screen.getByLabelText("Max Tokens"));
    await user.type(screen.getByLabelText("Max Tokens"), "256");
    await user.clear(screen.getByLabelText("Output Schema Ref"));
    await user.type(screen.getByLabelText("Output Schema Ref"), "incident-report/v1");

    await user.click(screen.getByRole("button", { name: /YAML/ }));

    const exportedYaml = screen.getByLabelText(/导出的 Workflow YAML|瀵煎嚭鐨.*Workflow YAML/) as HTMLTextAreaElement;
    expect(exportedYaml.value).toContain("model_policy_ref: prod-fast");
    expect(exportedYaml.value).toContain("prompt_template_ref: incident-summary");
    expect(exportedYaml.value).toContain("prompt_version: v2");
    expect(exportedYaml.value).toContain("max_tokens: 256");
    expect(exportedYaml.value).toContain("output_schema_ref: incident-report/v1");
    expect(screen.getByText(/tokens 32/)).toBeInTheDocument();
    expect(screen.getByText(/42ms/)).toBeInTheDocument();
    expect(screen.getByText(/sha256:sample-llm/)).toBeInTheDocument();
  });

  it("shows YAML v2 import diff and exports preserved loop metadata", async () => {
    const user = userEvent.setup();

    render(<WorkflowStudio project={defaultProjectContext} />);

    const yamlEditor = screen.getByLabelText("Workflow YAML");
    await user.clear(yamlEditor);
    fireEvent.change(
      yamlEditor,
      {
        target: {
          value: `schema_version: workflow.dsl/v0.2
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
    position: { x: 72, y: 180 }
  - id: router_1
    type: condition
    name: 风险路由
    position: { x: 320, y: 180 }
    data:
      expression: alert.severity
      cases: [collect, finish]
  - id: tool_1
    type: mcp_tool
    name: 查询 Pod 状态
    risk_level: medium
    position: { x: 610, y: 80 }
    parameters:
      namespace: ops
      dry_run: true
    tool_group_refs:
      - incident.write
    data:
      mcp_server_ref: cluster-observability
      tool_group_ref: kubernetes-readonly
      tool_name: kubectl_get_pods
      environment: staging
  - id: llm_1
    type: llm
    name: 汇总闭环
    risk_level: medium
    position: { x: 880, y: 180 }
    data:
      model_policy_ref: default
      prompt_template_ref: incident-summary
      prompt_version: v2
  - id: end_1
    type: end
    name: 输出报告
    position: { x: 1160, y: 180 }
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
`,
        },
      },
    );

    await user.click(screen.getAllByRole("button", { name: /预览|棰勮/ })[0]);

    expect(screen.getByText(/added node: router_1/)).toBeInTheDocument();
    expect(screen.getByText(/removed node: agent_1/)).toBeInTheDocument();
    expect(screen.getByText(/changed tool group: incident.write/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /应用|搴旂敤/ }));
    await user.click(screen.getByRole("button", { name: /YAML/ }));

    const exportedYaml = screen
      .getAllByLabelText(/Workflow YAML/)
      .find((element) => element.hasAttribute("readonly")) as HTMLTextAreaElement;
    expect(exportedYaml.value).toContain("schema_version: workflow.dsl/v0.2");
    expect(exportedYaml.value).toContain("kind: loop");
    expect(exportedYaml.value).toContain("parameters:");
  });

  it("adds nodes from the library, edits a loop edge, deletes canvas items, and exports v2 YAML", async () => {
    const user = userEvent.setup();

    render(<WorkflowStudio project={defaultProjectContext} />);

    await user.click(screen.getByRole("button", { name: "Add Condition node" }));
    await user.click(screen.getByRole("button", { name: "Add End node" }));

    expect(screen.getByText("Condition Router")).toBeInTheDocument();
    expect(screen.getByText("End Output")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Edge source"), "llm_1");
    await user.selectOptions(screen.getByLabelText("Edge target"), "condition_1");
    await user.selectOptions(screen.getByLabelText("Edge kind"), "loop");
    await user.click(screen.getByRole("button", { name: "Create edge" }));

    expect(screen.getByText("Selected Edge")).toBeInTheDocument();
    expect(screen.getByDisplayValue("loop")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Loop max iterations"));
    await user.type(screen.getByLabelText("Loop max iterations"), "5");
    await user.clear(screen.getByLabelText("Edge label"));
    await user.type(screen.getByLabelText("Edge label"), "refine");
    await user.clear(screen.getByLabelText("Source handle"));
    await user.type(screen.getByLabelText("Source handle"), "retry");

    await user.click(screen.getByRole("button", { name: "导出 YAML" }));
    let exportedYaml = screen.getByLabelText("导出的 Workflow YAML") as HTMLTextAreaElement;
    expect(exportedYaml.value).toContain("schema_version: workflow.dsl/v0.2");
    expect(exportedYaml.value).toContain("id: condition_1");
    expect(exportedYaml.value).toContain("kind: loop");
    expect(exportedYaml.value).toContain("source_handle: retry");
    expect(exportedYaml.value).toContain("max_iterations: 5");
    expect(exportedYaml.value).toContain("label: refine");

    await user.click(screen.getByRole("button", { name: "Delete selected edge" }));
    await user.click(screen.getByRole("button", { name: "导出 YAML" }));
    exportedYaml = screen.getByLabelText("导出的 Workflow YAML") as HTMLTextAreaElement;
    expect(exportedYaml.value).not.toContain("kind: loop");

    await user.selectOptions(screen.getByLabelText("Select node for inspector"), "condition_1");
    await user.click(screen.getByRole("button", { name: "Delete selected node" }));
    await user.click(screen.getByRole("button", { name: "导出 YAML" }));
    exportedYaml = screen.getByLabelText("导出的 Workflow YAML") as HTMLTextAreaElement;
    expect(exportedYaml.value).not.toContain("condition_1");
  });
});
