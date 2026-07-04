import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowStudio } from "./WorkflowStudio";
import { defaultProjectContext } from "../../shell/projectContext";

const projectUuid = "11111111-1111-4111-8111-111111111111";
const accountUuid = "22222222-2222-4222-8222-222222222222";

afterEach(() => {
  vi.restoreAllMocks();
});

function renderWorkflowStudio() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <WorkflowStudio project={defaultProjectContext} />
    </QueryClientProvider>,
  );
}

describe("WorkflowStudio", () => {
  it("previews imported YAML, applies it to the canvas, renames a node, and exports YAML", async () => {
    const user = userEvent.setup();

    renderWorkflowStudio();

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

    renderWorkflowStudio();

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

    renderWorkflowStudio();

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

    renderWorkflowStudio();

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

  it("checks publish gates, publishes versions, restores drafts, and archives with confirmation", async () => {
    const user = userEvent.setup();
    let restoredDraft: ReturnType<typeof makeDraft> | null = null;
    let versionStatus: "published" | "archived" = "published";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);

      if (url.endsWith("/workflows/drafts") && !init) {
        return jsonResponse({
          drafts: [
            ...(restoredDraft ? [restoredDraft] : []),
            makeDraft({
              id: "33333333-3333-4333-8333-333333333333",
              status: "draft",
              version: 1,
            }),
          ],
        });
      }
      if (url.endsWith("/workflows/versions?workflow_id=ops_incident_triage") && !init) {
        return jsonResponse({
          count: 1,
          versions: [
            makeVersion({
              definitionHash: "sha256:published-v1",
              id: "44444444-4444-4444-8444-444444444444",
              releaseNote: "Initial guarded release",
              status: versionStatus,
              version: 1,
            }),
          ],
        });
      }
      if (url.endsWith("/drafts/33333333-3333-4333-8333-333333333333") && init?.method === "PUT") {
        return jsonResponse(makeDraft({ id: "33333333-3333-4333-8333-333333333333", version: 1 }));
      }
      if (url.endsWith("/drafts/55555555-5555-4555-8555-555555555555") && init?.method === "PUT") {
        return jsonResponse(
          makeDraft({
            id: "55555555-5555-4555-8555-555555555555",
            name: "Restored incident workflow",
            version: 2,
          }),
        );
      }
      if (url.endsWith("/publish-check")) {
        return jsonResponse({
          can_create_draft: true,
          can_publish_or_run: false,
          import_diff: {
            added_edges: [],
            added_nodes: [],
            changed_tool_groups: [],
            has_breaking_changes: false,
            modified_nodes: [],
            removed_edges: [],
            removed_nodes: [],
          },
          missing_references: [
            { reference: "collect-pod-logs@1", reference_type: "shell_template" },
          ],
          permission_impact: {
            approval_required: false,
            environments: ["staging"],
            mcp_servers: [],
            risk_levels: ["medium"],
            shell_templates: ["collect-pod-logs@1"],
            tool_groups: [],
          },
        });
      }
      if (url.endsWith("/publish")) {
        return jsonResponse(
          {
            detail: {
              can_publish: false,
              reasons: [
                {
                  code: "missing_reference",
                  message: "Shell template collect-pod-logs@1 is missing",
                  node_id: "shell_1",
                  reference: "collect-pod-logs@1",
                  reference_type: "shell_template",
                  severity: "blocker",
                },
              ],
            },
          },
          { status: 422 },
        );
      }
      if (url.endsWith("/versions/44444444-4444-4444-8444-444444444444/restore-draft")) {
        restoredDraft = makeDraft({
          id: "55555555-5555-4555-8555-555555555555",
          name: "Restored incident workflow",
          version: 2,
        });
        return jsonResponse(
          restoredDraft,
          { status: 201 },
        );
      }
      if (url.endsWith("/versions/44444444-4444-4444-8444-444444444444/archive")) {
        versionStatus = "archived";
        return jsonResponse(
          makeVersion({
            definitionHash: "sha256:published-v1",
            id: "44444444-4444-4444-8444-444444444444",
            releaseNote: "Initial guarded release",
            status: "archived",
            version: 1,
          }),
        );
      }

      return jsonResponse({ detail: `Unexpected request ${url}` }, { status: 500 });
    });

    renderWorkflowStudio();

    expect(await screen.findByText("Workflow Release")).toBeInTheDocument();
    expect(await screen.findByText("Initial guarded release")).toBeInTheDocument();
    expect(screen.getByText(/Run binds to version 1/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "发布检查" }));
    expect((await screen.findAllByText("shell_template: collect-pod-logs@1")).length).toBeGreaterThan(0);
    expect(screen.getByText("发布门禁未通过")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Release note"));
    await user.type(screen.getByLabelText("Release note"), "Ship guarded workflow");
    await user.click(screen.getByRole("button", { name: "发布版本" }));

    expect(await screen.findByText("missing_reference")).toBeInTheDocument();
    expect(screen.getByText("Shell template collect-pod-logs@1 is missing")).toBeInTheDocument();
    expect(screen.queryByText(/raw prompt/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Restore version 1 as draft" }));
    expect(await screen.findByText("Restored incident workflow")).toBeInTheDocument();
    expect(screen.getByText(/Restored as draft v2/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "发布检查" }));
    const restoredDraftUpdateCall = fetchMock.mock.calls.some(
      ([url, init]) =>
        String(url).includes("/workflows/drafts/55555555-5555-4555-8555-555555555555") &&
        init?.method === "PUT",
    );
    expect(restoredDraftUpdateCall).toBe(true);

    await user.click(screen.getByRole("button", { name: "Archive version 1" }));
    await user.type(screen.getByLabelText("Archive reason"), "Superseded by restored draft");
    await user.click(screen.getByRole("button", { name: "Confirm archive version 1" }));

    expect(await screen.findByText("archived")).toBeInTheDocument();
    expect(screen.getByText(/No published version selected for run/)).toBeInTheDocument();

    const updateCalls = fetchMock.mock.calls.filter(
      ([url, init]) => String(url).includes("/workflows/drafts/") && init?.method === "PUT",
    );
    expect(updateCalls.length).toBeGreaterThanOrEqual(2);
    const publishCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/publish"));
    expect(JSON.parse(String(publishCall?.[1]?.body))).toEqual({
      release_note: "Ship guarded workflow",
    });
  });

  it("runs the selected published version and links checkpoints to Run Observatory", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);

      if (url.endsWith("/workflows/drafts") && !init) {
        return jsonResponse({
          drafts: [
            makeDraft({
              id: "33333333-3333-4333-8333-333333333333",
              status: "draft",
              version: 1,
            }),
          ],
        });
      }
      if (url.endsWith("/workflows/versions?workflow_id=ops_incident_triage") && !init) {
        return jsonResponse({
          count: 1,
          versions: [
            makeVersion({
              definitionHash: "sha256:published-v1",
              id: "44444444-4444-4444-8444-444444444444",
              releaseNote: "Initial guarded release",
              status: "published",
              version: 1,
            }),
          ],
        });
      }
      if (
        url.endsWith("/workflows/versions/44444444-4444-4444-8444-444444444444/runs") &&
        init?.method === "POST"
      ) {
        return jsonResponse(
          {
            id: "run-row-1",
            project_id: "ops-command",
            workflow_version_id: "44444444-4444-4444-8444-444444444444",
            workflow_ref: "ops_incident_triage:1",
            run_id: "run-ui",
            trace_id: "trace-ui",
            status: "pending_approval",
            outputs: {},
            node_results: [],
            pending_approval: {
              approval_kind: "human",
              approval_policy_ref: "ops.approval",
              approval_task_id: "approval-ui",
              message: "Human approval required",
              node_id: "human_approval_1",
              node_name: "Approve rollout",
              payload: {},
            },
            error_type: "",
            error_message: "",
            created_at: "2026-07-04T00:00:00Z",
            updated_at: "2026-07-04T00:00:01Z",
          },
          { status: 201 },
        );
      }
      if (
        url.endsWith(
          "/workflows/versions/44444444-4444-4444-8444-444444444444/runs/run-ui",
        ) &&
        !init
      ) {
        return jsonResponse(workflowRunDetailFixture());
      }
      if (
        url.endsWith(
          "/workflows/versions/44444444-4444-4444-8444-444444444444/runs?limit=20",
        ) &&
        !init
      ) {
        return jsonResponse({
          count: 1,
          runs: [workflowRunDetailFixture().run],
        });
      }
      if (
        url.endsWith(
          "/workflows/versions/44444444-4444-4444-8444-444444444444/runs/run-ui/resume",
        ) &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          id: "run-row-1",
          project_id: "ops-command",
          workflow_version_id: "44444444-4444-4444-8444-444444444444",
          workflow_ref: "ops_incident_triage:1",
          run_id: "run-ui",
          trace_id: "trace-ui",
          status: "success",
          outputs: { approved: true },
          node_results: [],
          pending_approval: null,
          error_type: "",
          error_message: "",
          created_at: "2026-07-04T00:00:00Z",
          updated_at: "2026-07-04T00:00:02Z",
        });
      }

      return jsonResponse({ detail: `Unexpected request ${url}` }, { status: 500 });
    });

    renderWorkflowStudio();

    expect(await screen.findByText("Workflow Release")).toBeInTheDocument();
    expect(await screen.findByText(/Run binds to version 1/)).toBeInTheDocument();
    expect(screen.getByText("Workflow Run")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Run inputs JSON"), {
      target: { value: '{ "change_id": "CHG-123" }' },
    });
    await user.click(screen.getByRole("button", { name: "Run published version" }));

    expect((await screen.findAllByText("pending_approval")).length).toBeGreaterThan(0);
    expect(screen.getByText("Human approval required")).toBeInTheDocument();
    expect(screen.getAllByText("human_approval_1").length).toBeGreaterThan(0);
    expect(await screen.findByText("Run History")).toBeInTheDocument();
    expect(screen.getAllByText("run-ui").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Resume payload JSON")).toHaveValue("{\n}");
    await user.click(screen.getByRole("button", { name: "Approve Resume" }));
    expect(
      globalThis.fetch,
    ).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/44444444-4444-4444-8444-444444444444/runs/run-ui/resume",
      expect.objectContaining({
        body: JSON.stringify({ decision: "approved", payload: {} }),
        method: "POST",
      }),
    );
    expect(screen.getByRole("link", { name: "Open Run Observatory" })).toHaveAttribute(
      "href",
      "/projects/ops-command/runs?run_id=run-ui&trace_id=trace-ui&version_id=44444444-4444-4444-8444-444444444444",
    );
    expect(screen.queryByText("raw-secret-token")).not.toBeInTheDocument();
  });
});

function jsonResponse(body: unknown, init: ResponseInit = { status: 200 }) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

function makeDraft({
  id,
  name = "Kubernetes incident workflow",
  status = "draft",
  version,
}: {
  id: string;
  name?: string;
  status?: "draft" | "published" | "archived";
  version: number;
}) {
  return {
    analysis: {
      can_create_draft: true,
      can_publish_or_run: true,
      import_diff: {
        added_edges: [],
        added_nodes: [],
        changed_tool_groups: [],
        has_breaking_changes: false,
        modified_nodes: [],
        removed_edges: [],
        removed_nodes: [],
      },
      missing_references: [],
      permission_impact: {
        approval_required: false,
        environments: ["staging"],
        mcp_servers: ["cluster-observability"],
        risk_levels: ["medium"],
        shell_templates: [],
        tool_groups: ["kubernetes-readonly"],
      },
    },
    can_publish_or_run: true,
    created_at: "2026-07-04T08:00:00Z",
    created_by: accountUuid,
    definition: {
      schema_version: "workflow.dsl/v0.2",
      workflow: {
        id: "ops_incident_triage",
        name,
        project_id: "ops-command",
        status,
        version,
      },
      nodes: [
        { id: "start_1", name: "Start", type: "start" },
        { id: "end_1", name: "End", type: "end" },
      ],
      edges: [{ source: "start_1", target: "end_1", kind: "sequence" }],
    },
    id,
    name,
    project_id: projectUuid,
    status,
    updated_at: "2026-07-04T08:00:00Z",
    updated_by: accountUuid,
    version,
    workflow_id: "ops_incident_triage",
  };
}

function makeVersion({
  definitionHash,
  id,
  releaseNote,
  status,
  version,
}: {
  definitionHash: string;
  id: string;
  releaseNote: string;
  status: "published" | "archived";
  version: number;
}) {
  return {
    ...makeDraft({
      id,
      status,
      version,
    }),
    archived_at: status === "archived" ? "2026-07-04T09:00:00Z" : null,
    archived_by: status === "archived" ? accountUuid : null,
    definition_hash: definitionHash,
    gate_result: {
      can_publish: true,
      reasons: [],
    },
    published_by: accountUuid,
    release_note: releaseNote,
    status,
  };
}

function workflowRunDetailFixture() {
  return {
    run: {
      actor_id: accountUuid,
      created_at: "2026-07-04T00:00:00Z",
      created_by: accountUuid,
      definition_hash: "sha256:published-v1",
      error_message: "",
      error_type: "",
      id: "run-row-1",
      inputs_summary: "change_id",
      outputs_summary: "awaiting approval",
      pending_approval: {
        approval_policy_ref: "ops.approval",
        approval_task_id: "approval-ui",
        message: "Human approval required",
        node_id: "human_approval_1",
        node_name: "Approve rollout",
      },
      project_id: projectUuid,
      run_id: "run-ui",
      status: "pending_approval",
      trace_id: "trace-ui",
      updated_at: "2026-07-04T00:00:01Z",
      updated_by: accountUuid,
      workflow_id: "ops_incident_triage",
      workflow_ref: "ops_incident_triage:1",
      workflow_version_id: "44444444-4444-4444-8444-444444444444",
    },
    checkpoints: [
      {
        actor_id: accountUuid,
        created_at: "2026-07-04T00:00:00Z",
        created_by: accountUuid,
        error_message: "",
        error_type: "",
        id: "checkpoint-1",
        node_id: "human_approval_1",
        node_type: "human_approval",
        output: { summary: "awaiting approval", token: "raw-secret-token" },
        project_id: projectUuid,
        run_id: "run-ui",
        state: {},
        status: "pending_approval",
        trace_id: "trace-ui",
        updated_at: "2026-07-04T00:00:01Z",
        updated_by: accountUuid,
        workflow_ref: "ops_incident_triage:1",
        workflow_run_id: "run-row-1",
        workflow_version_id: "44444444-4444-4444-8444-444444444444",
      },
    ],
  };
}
