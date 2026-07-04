import { describe, expect, it, vi } from "vitest";

import {
  cancelWorkflowRun,
  getWorkflowRunDetail,
  listWorkflowRunEvents,
  listWorkflowRuns,
  retryWorkflowRun,
  resumeWorkflowRun,
  runWorkflowVersion,
  submitWorkflowVersionRun,
  workflowRunDetailQueryKey,
  workflowRunEventsQueryKey,
  workflowRunListQueryKey,
} from "./workflowRuntimeApi";

describe("workflowRuntimeApi", () => {
  it("builds stable run detail query keys", () => {
    expect(workflowRunDetailQueryKey("ops-command", "version-1", "run-1")).toEqual([
      "project",
      "ops-command",
      "workflows",
      "versions",
      "version-1",
      "runs",
      "run-1",
    ]);
  });

  it("builds stable run list query keys", () => {
    expect(workflowRunListQueryKey("ops-command", "version-1", "pending_approval")).toEqual([
      "project",
      "ops-command",
      "workflows",
      "versions",
      "version-1",
      "runs",
      "list",
      "pending_approval",
    ]);
  });

  it("builds stable runtime event query keys", () => {
    expect(workflowRunEventsQueryKey("ops-command", "version-1", "run-1")).toEqual([
      "project",
      "ops-command",
      "workflows",
      "versions",
      "version-1",
      "runs",
      "run-1",
      "events",
    ]);
  });

  it("starts a workflow version run with inputs, run ref, and trace id", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(workflowRunResult()), { status: 201 }),
    );

    const response = await runWorkflowVersion(
      "ops-command",
      "version-1",
      {
        inputs: { change_id: "CHG-123" },
        run_ref: "run-1",
        trace_id: "trace-1",
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs",
      {
        body: JSON.stringify({
          inputs: { change_id: "CHG-123" },
          run_ref: "run-1",
          trace_id: "trace-1",
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      },
    );
    expect(response.run_id).toBe("run-1");
  });

  it("submits a workflow version run for background execution", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ...workflowRunDetail().run, status: "queued" }), {
        status: 202,
      }),
    );

    const response = await submitWorkflowVersionRun(
      "ops-command",
      "version-1",
      {
        inputs: { change_id: "CHG-123" },
        run_ref: "run-1",
        trace_id: "trace-1",
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs/submit",
      {
        body: JSON.stringify({
          inputs: { change_id: "CHG-123" },
          run_ref: "run-1",
          trace_id: "trace-1",
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      },
    );
    expect(response.status).toBe("queued");
  });

  it("loads workflow run detail with checkpoints", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(workflowRunDetail()), { status: 200 }),
    );

    const response = await getWorkflowRunDetail("ops-command", "version-1", "run-1", fetcher);

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs/run-1",
    );
    expect(response.run.status).toBe("pending_approval");
    expect(response.checkpoints[0].node_id).toBe("human_approval_1");
  });

  it("lists workflow runs for a version", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ count: 1, runs: [workflowRunDetail().run] }), { status: 200 }),
    );

    const response = await listWorkflowRuns(
      "ops-command",
      "version-1",
      { limit: 10, status: "pending_approval" },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs?limit=10&status=pending_approval",
    );
    expect(response.count).toBe(1);
    expect(response.runs[0].run_id).toBe("run-1");
  });

  it("lists workflow run events with an incremental cursor", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          count: 1,
          events: [
            {
              actor_id: "acct-1",
              created_at: "2026-07-04T00:00:00Z",
              created_by: "acct-1",
              event_type: "node.completed",
              id: "event-1",
              message: "workflow node success",
              node_id: "llm_1",
              node_type: "llm",
              payload: {},
              payload_summary: "safe summary",
              project_id: "ops-command",
              run_id: "run-1",
              sequence: 2,
              status: "success",
              trace_id: "trace-1",
              updated_at: "2026-07-04T00:00:00Z",
              updated_by: "acct-1",
              workflow_ref: "ops_incident_triage:1",
              workflow_run_id: "run-row-1",
              workflow_version_id: "version-1",
            },
          ],
        }),
        { status: 200 },
      ),
    );

    const response = await listWorkflowRunEvents(
      "ops-command",
      "version-1",
      "run-1",
      { after_sequence: 1, limit: 50 },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs/run-1/events?after_sequence=1&limit=50",
    );
    expect(response.events[0].event_type).toBe("node.completed");
  });

  it("resumes a pending workflow run", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(workflowRunResult({ status: "success" })), { status: 200 }),
    );

    const response = await resumeWorkflowRun(
      "ops-command",
      "version-1",
      "run-1",
      { decision: "approved", payload: { reason: "ok" } },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs/run-1/resume",
      {
        body: JSON.stringify({ decision: "approved", payload: { reason: "ok" } }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      },
    );
    expect(response.status).toBe("success");
  });

  it("cancels a pending workflow run", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ...workflowRunDetail().run, status: "cancelled" }), {
        status: 200,
      }),
    );

    const response = await cancelWorkflowRun(
      "ops-command",
      "version-1",
      "run-1",
      { reason: "operator stopped approval" },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs/run-1/cancel",
      {
        body: JSON.stringify({ reason: "operator stopped approval" }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      },
    );
    expect(response.status).toBe("cancelled");
  });

  it("retries a terminal workflow run", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(workflowRunResult({ run_id: "run-retry" })), { status: 201 }),
    );

    const response = await retryWorkflowRun(
      "ops-command",
      "version-1",
      "run-1",
      { run_ref: "run-retry", trace_id: "trace-retry" },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-1/runs/run-1/retry",
      {
        body: JSON.stringify({ run_ref: "run-retry", trace_id: "trace-retry" }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      },
    );
    expect(response.run_id).toBe("run-retry");
  });

  it("throws useful backend details for failed run requests", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Workflow run not found" }), { status: 404 }),
    );

    await expect(getWorkflowRunDetail("ops-command", "version-1", "missing", fetcher)).rejects.toThrow(
      "Workflow run not found",
    );
  });
});

function workflowRunResult(overrides: Partial<ReturnType<typeof workflowRunResultBase>> = {}) {
  return {
    ...workflowRunResultBase(),
    ...overrides,
  };
}

function workflowRunResultBase() {
  return {
    id: "run-row-1",
    project_id: "ops-command",
    workflow_version_id: "version-1",
    workflow_ref: "ops_incident_triage:1",
    run_id: "run-1",
    trace_id: "trace-1",
    status: "pending_approval",
    outputs: {},
    node_results: [],
    pending_approval: {
      node_id: "human_approval_1",
      node_name: "Approve rollout",
      approval_policy_ref: "ops.approval",
      message: "Human approval required",
      approval_kind: "human",
      approval_task_id: "approval-1",
      payload: {},
    },
    error_type: "",
    error_message: "",
    created_at: "2026-07-04T00:00:00Z",
    updated_at: "2026-07-04T00:00:00Z",
  };
}

function workflowRunDetail() {
  return {
    run: {
      actor_id: "acct-1",
      created_by: "acct-1",
      definition_hash: "sha256:published-v1",
      error_message: "",
      error_type: "",
      id: "run-row-1",
      inputs_summary: "change_id",
      outputs_summary: "awaiting approval",
      pending_approval: {
        approval_policy_ref: "ops.approval",
        approval_task_id: "approval-1",
        message: "Human approval required",
        node_id: "human_approval_1",
        node_name: "Approve rollout",
      },
      project_id: "ops-command",
      run_id: "run-1",
      status: "pending_approval",
      trace_id: "trace-1",
      updated_by: "acct-1",
      workflow_id: "ops_incident_triage",
      workflow_ref: "ops_incident_triage:1",
      workflow_version_id: "version-1",
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:01Z",
    },
    checkpoints: [
      {
        actor_id: "acct-1",
        created_by: "acct-1",
        error_message: "",
        error_type: "",
        id: "checkpoint-1",
        node_id: "human_approval_1",
        node_type: "human_approval",
        output: { summary: "awaiting approval" },
        project_id: "ops-command",
        run_id: "run-1",
        state: {},
        status: "pending_approval",
        trace_id: "trace-1",
        updated_by: "acct-1",
        workflow_ref: "ops_incident_triage:1",
        workflow_run_id: "run-row-1",
        workflow_version_id: "version-1",
        created_at: "2026-07-04T00:00:00Z",
        updated_at: "2026-07-04T00:00:01Z",
      },
    ],
  };
}
