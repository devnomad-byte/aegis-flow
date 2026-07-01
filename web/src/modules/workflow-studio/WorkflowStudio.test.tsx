import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("shell_template: collect-pod-logs@1.0.0")).toBeInTheDocument();
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
});
