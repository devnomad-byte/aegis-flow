import "@xyflow/react/dist/style.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ComponentType, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type EdgeMouseHandler,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import {
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  Download,
  FileSearch,
  GitBranch,
  Import,
  Link2,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import { SAMPLE_CATALOG, SAMPLE_WORKFLOW, SAMPLE_WORKFLOW_YAML } from "./sampleWorkflow";
import {
  getWorkflowRunDetail,
  runWorkflowVersion,
  workflowRunDetailQueryKey,
  type WorkflowNodeStatus,
  type WorkflowPendingApproval,
  type WorkflowRunCheckpointRead,
  type WorkflowRunDetailResponse,
  type WorkflowRunResult,
  type WorkflowRunStatus,
} from "../workflow-runtime/workflowRuntimeApi";
import {
  WorkflowPublishGateError,
  archiveWorkflowVersion,
  listWorkflowDrafts,
  listWorkflowVersions,
  publishCheckWorkflowDraft,
  publishWorkflowDraft,
  restoreWorkflowVersionAsDraft,
  updateWorkflowDraft,
  workflowDraftsQueryKey,
  workflowVersionsQueryKey,
  type WorkflowDraftListResponse,
  type WorkflowDraftRead,
  type WorkflowPublishGateResult,
  type WorkflowVersionListResponse,
  type WorkflowVersionRead,
} from "./workflowApi";
import {
  buildImportPreviewSummary,
  createWorkflowEdge,
  createWorkflowNode,
  deleteWorkflowEdge,
  deleteWorkflowNode,
  ensureWorkflowV2,
  getLlmNodeData,
  getWorkflowEdgeIdentity,
  renameWorkflowNode,
  updateWorkflowEdge,
  updateWorkflowNodeData,
  workflowToFlow,
} from "./workflowDsl";
import { exportWorkflowYaml, previewWorkflowImportFromYaml } from "./workflowYaml";
import { WorkflowNode } from "./WorkflowNode";
import type { ProjectContext } from "../../shell/projectContext";
import type {
  EdgeDefinition,
  EdgeKind,
  ImportPreviewSummary,
  NodeType,
  WorkflowDefinition,
  WorkflowFlowNode,
  WorkflowImportAnalysis,
  WorkflowImportPreview,
} from "./workflowTypes";

type WorkflowStudioProps = {
  project: ProjectContext;
};

type TimelineEvent = {
  time: string;
  label: string;
  state: "ok" | "pending" | "blocked";
};

type LlmTraceEvent = {
  nodeId: string;
  status: "success" | "failed" | "budget_exceeded";
  model: string;
  requestHash: string;
  latencyMs: number;
  totalTokens: number;
};

type NodeLibraryItem = {
  type: NodeType;
  label: string;
  description: string;
  icon: ComponentType<{ size?: number }>;
};

type EdgeComposerState = {
  source: string;
  target: string;
  kind: EdgeKind;
};

type PublishStatus = {
  kind: "idle" | "checked" | "published" | "restored" | "archived" | "error";
  message: string;
};

type RunTarget = {
  runId: string;
  traceId: string;
  versionId: string;
};

const nodeTypes = {
  workflowNode: WorkflowNode,
};

const initialPreview = previewWorkflowImportFromYaml(SAMPLE_WORKFLOW_YAML, SAMPLE_CATALOG);
const sampleLlmTraceEvents: LlmTraceEvent[] = [
  {
    nodeId: "llm_1",
    status: "success",
    model: "gpt-5.5",
    requestHash: "sha256:sample-llm",
    latencyMs: 42,
    totalTokens: 32,
  },
];
const NODE_LIBRARY_ITEMS: NodeLibraryItem[] = [
  {
    type: "start",
    label: "Start",
    description: "Entry point",
    icon: CircleDot,
  },
  {
    type: "llm",
    label: "LLM",
    description: "Model policy",
    icon: BrainCircuit,
  },
  {
    type: "condition",
    label: "Condition",
    description: "Branch route",
    icon: GitBranch,
  },
  {
    type: "mcp_tool",
    label: "MCP Tool",
    description: "Tool gateway",
    icon: Bot,
  },
  {
    type: "human_approval",
    label: "Human Approval",
    description: "Risk gate",
    icon: ShieldCheck,
  },
  {
    type: "end",
    label: "End",
    description: "Final output",
    icon: CheckCircle2,
  },
];
const EDGE_KIND_OPTIONS: Array<{ label: string; value: EdgeKind }> = [
  { label: "sequence", value: "sequence" },
  { label: "condition", value: "condition" },
  { label: "parallel", value: "parallel" },
  { label: "loop", value: "loop" },
  { label: "resume", value: "resume" },
];
const EMPTY_DRAFTS: WorkflowDraftRead[] = [];

export function WorkflowStudio({ project }: WorkflowStudioProps) {
  const queryClient = useQueryClient();
  const [workflow, setWorkflow] = useState<WorkflowDefinition>(SAMPLE_WORKFLOW);
  const [selectedNodeId, setSelectedNodeId] = useState<string>(
    SAMPLE_WORKFLOW.nodes.find((node) => node.type === "llm")?.id ?? SAMPLE_WORKFLOW.nodes[1].id,
  );
  const [yamlText, setYamlText] = useState(SAMPLE_WORKFLOW_YAML);
  const [preview, setPreview] = useState<WorkflowImportPreview | null>(initialPreview);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [exportedYaml, setExportedYaml] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const [edgeComposer, setEdgeComposer] = useState<EdgeComposerState>(
    buildDefaultEdgeComposer(SAMPLE_WORKFLOW),
  );
  const [edgeComposerError, setEdgeComposerError] = useState<string | null>(null);
  const [releaseNote, setReleaseNote] = useState("");
  const [archiveReason, setArchiveReason] = useState("");
  const [confirmArchiveVersionId, setConfirmArchiveVersionId] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [publishGateResult, setPublishGateResult] = useState<WorkflowPublishGateResult | null>(null);
  const [publishCheckAnalysis, setPublishCheckAnalysis] = useState<WorkflowImportAnalysis | null>(null);
  const [publishStatus, setPublishStatus] = useState<PublishStatus>({
    kind: "idle",
    message: "",
  });
  const [runInputsText, setRunInputsText] = useState("{\n}");
  const [runInputsError, setRunInputsError] = useState("");
  const [latestRunTarget, setLatestRunTarget] = useState<RunTarget | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([
    { time: "00:00.000", label: "Workflow DSL loaded", state: "ok" },
    { time: "00:00.146", label: "Project catalog analyzed", state: "ok" },
    { time: "00:00.318", label: "Shell template waiting for project config", state: "pending" },
  ]);

  const previewSummary = useMemo(
    () => (preview ? buildImportPreviewSummary(preview.analysis) : null),
    [preview],
  );
  const draftsQueryKey = workflowDraftsQueryKey(project.projectId);
  const draftsQuery = useQuery({
    queryFn: () => listWorkflowDrafts(project.projectId),
    queryKey: draftsQueryKey,
  });
  const drafts = draftsQuery.data?.drafts ?? EMPTY_DRAFTS;
  const activeDraft = useMemo(
    () =>
      drafts.find(
        (draft) =>
          draft.workflow_id === workflow.workflow.id &&
          draft.version === workflow.workflow.version,
      ) ??
      drafts.find((draft) => draft.workflow_id === workflow.workflow.id) ??
      drafts[0] ??
      null,
    [drafts, workflow.workflow.id, workflow.workflow.version],
  );
  useEffect(() => {
    if (!activeDraft) {
      return;
    }
    if (
      workflow.workflow.id === SAMPLE_WORKFLOW.workflow.id &&
      activeDraft.workflow_id !== workflow.workflow.id
    ) {
      setWorkflow(activeDraft.definition);
      setSelectedNodeId(activeDraft.definition.nodes[0]?.id ?? "");
      setSelectedEdgeId("");
      setEdgeComposer(buildDefaultEdgeComposer(activeDraft.definition));
      setPreview((currentPreview) =>
        currentPreview
          ? { ...currentPreview, analysis: activeDraft.analysis, workflow: activeDraft.definition }
          : { analysis: activeDraft.analysis, workflow: activeDraft.definition },
      );
    }
  }, [activeDraft, workflow.workflow.id]);

  const versionWorkflowId = activeDraft?.workflow_id ?? workflow.workflow.id;
  const versionsQueryKey = workflowVersionsQueryKey(project.projectId, versionWorkflowId);
  const versionsQuery = useQuery({
    enabled: Boolean(versionWorkflowId),
    queryFn: () => listWorkflowVersions(project.projectId, versionWorkflowId),
    queryKey: versionsQueryKey,
  });
  const versions = versionsQuery.data?.versions ?? [];
  const selectedVersion =
    versions.find((version) => version.id === selectedVersionId) ??
    versions.find((version) => version.status === "published") ??
    null;

  const flow = useMemo(() => workflowToFlow(workflow, preview?.analysis), [preview?.analysis, workflow]);
  const flowEdges = useMemo(
    () => flow.edges.map((edge) => ({ ...edge, selected: edge.id === selectedEdgeId })),
    [flow.edges, selectedEdgeId],
  );
  const nodeOptions = useMemo(
    () =>
      workflow.nodes.map((node) => ({
        label: `${node.name} (${node.id})`,
        value: node.id,
      })),
    [workflow.nodes],
  );
  const selectedNode = useMemo(
    () => workflow.nodes.find((node) => node.id === selectedNodeId) ?? workflow.nodes[0],
    [selectedNodeId, workflow.nodes],
  );
  const selectedEdge = useMemo(
    () => workflow.edges.find((edge) => getWorkflowEdgeIdentity(edge) === selectedEdgeId) ?? null,
    [selectedEdgeId, workflow.edges],
  );
  const selectedFlowNode = flow.nodes.find((node) => node.id === selectedNode.id);
  const selectedLlmTraceEvents = sampleLlmTraceEvents.filter(
    (event) => event.nodeId === selectedNode.id,
  );

  const publishCheckMutation = useMutation({
    mutationFn: async () => {
      if (!activeDraft) {
        throw new Error("No active workflow draft is available for publish-check.");
      }
      const savedDraft = await updateWorkflowDraft(
        project.projectId,
        activeDraft.id,
        ensureWorkflowV2(workflow),
      );
      const analysis = await publishCheckWorkflowDraft(project.projectId, savedDraft.id);
      return { analysis, savedDraft };
    },
    onSuccess: ({ analysis, savedDraft }) => {
      setWorkflow(savedDraft.definition);
      setPublishCheckAnalysis(analysis);
      setPublishGateResult(null);
      setPublishStatus({
        kind: "checked",
        message: analysis.can_publish_or_run ? "发布门禁通过" : "发布门禁未通过",
      });
      setPreview((currentPreview) =>
        currentPreview
          ? { ...currentPreview, analysis, workflow: savedDraft.definition }
          : { analysis, workflow: savedDraft.definition },
      );
      void queryClient.invalidateQueries({ queryKey: draftsQueryKey });
    },
    onError: (error) => {
      setPublishStatus({ kind: "error", message: getErrorMessage(error) });
    },
  });
  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!activeDraft) {
        throw new Error("No active workflow draft is available for publish.");
      }
      const savedDraft = await updateWorkflowDraft(
        project.projectId,
        activeDraft.id,
        ensureWorkflowV2(workflow),
      );
      const version = await publishWorkflowDraft(project.projectId, savedDraft.id, {
        release_note: releaseNote,
      });
      return { savedDraft, version };
    },
    onSuccess: ({ savedDraft, version }) => {
      setWorkflow(savedDraft.definition);
      setSelectedVersionId(version.id);
      setPublishGateResult(null);
      setReleaseNote("");
      setPublishStatus({
        kind: "published",
        message: `Published version ${version.version}`,
      });
      void queryClient.invalidateQueries({ queryKey: draftsQueryKey });
      void queryClient.invalidateQueries({ queryKey: versionsQueryKey });
    },
    onError: (error) => {
      if (error instanceof WorkflowPublishGateError) {
        setPublishGateResult(error.gateResult);
        setPublishStatus({ kind: "error", message: "发布门禁未通过" });
        return;
      }
      setPublishStatus({ kind: "error", message: getErrorMessage(error) });
    },
  });
  const restoreMutation = useMutation({
    mutationFn: (version: WorkflowVersionRead) =>
      restoreWorkflowVersionAsDraft(project.projectId, version.id, {
        release_note: `Restore published version ${version.version}`,
      }),
    onSuccess: (draft) => {
      setWorkflow(draft.definition);
      setSelectedNodeId(draft.definition.nodes[0]?.id ?? "");
      setSelectedEdgeId("");
      setEdgeComposer(buildDefaultEdgeComposer(draft.definition));
      setPublishGateResult(null);
      setPublishCheckAnalysis(draft.analysis);
      setPublishStatus({
        kind: "restored",
        message: `Restored as draft v${draft.version}`,
      });
      queryClient.setQueryData<WorkflowDraftListResponse>(draftsQueryKey, (current) => {
        const currentDrafts = current?.drafts ?? EMPTY_DRAFTS;
        const nextDrafts = currentDrafts.some((currentDraft) => currentDraft.id === draft.id)
          ? currentDrafts.map((currentDraft) => (currentDraft.id === draft.id ? draft : currentDraft))
          : [draft, ...currentDrafts];

        return { drafts: nextDrafts };
      });
      void queryClient.invalidateQueries({ queryKey: draftsQueryKey });
      void queryClient.invalidateQueries({
        queryKey: workflowVersionsQueryKey(project.projectId, draft.workflow_id),
      });
    },
    onError: (error) => {
      setPublishStatus({ kind: "error", message: getErrorMessage(error) });
    },
  });
  const archiveMutation = useMutation({
    mutationFn: (version: WorkflowVersionRead) =>
      archiveWorkflowVersion(project.projectId, version.id, { reason: archiveReason }),
    onSuccess: (version) => {
      setArchiveReason("");
      setConfirmArchiveVersionId("");
      if (selectedVersionId === version.id) {
        setSelectedVersionId("");
      }
      setPublishStatus({
        kind: "archived",
        message: `Archived version ${version.version}`,
      });
      queryClient.setQueryData<WorkflowVersionListResponse>(versionsQueryKey, (current) => {
        if (!current) {
          return current;
        }

        return {
          count: current.count,
          versions: current.versions.map((currentVersion) =>
            currentVersion.id === version.id ? version : currentVersion,
          ),
        };
      });
      void queryClient.invalidateQueries({ queryKey: versionsQueryKey });
    },
    onError: (error) => {
      setPublishStatus({ kind: "error", message: getErrorMessage(error) });
    },
  });
  const runMutation = useMutation({
    mutationFn: async () => {
      if (!selectedVersion || selectedVersion.status !== "published") {
        throw new Error("No published workflow version is selected.");
      }
      const inputs = parseRunInputs(runInputsText);
      return runWorkflowVersion(project.projectId, selectedVersion.id, { inputs });
    },
    onSuccess: (run) => {
      setRunInputsError("");
      setLatestRunTarget({
        runId: run.run_id,
        traceId: run.trace_id,
        versionId: run.workflow_version_id,
      });
      setTimelineEvents((events) => [
        {
          time: "00:02.000",
          label: `Workflow run ${run.run_id} ${run.status}`,
          state: run.status === "success" ? "ok" : run.status === "failed" ? "blocked" : "pending",
        },
        ...events.slice(0, 4),
      ]);
      void queryClient.invalidateQueries({
        queryKey: workflowRunDetailQueryKey(
          project.projectId,
          run.workflow_version_id,
          run.run_id,
        ),
      });
    },
    onError: (error) => {
      setRunInputsError(getErrorMessage(error));
    },
  });
  const runDetailQuery = useQuery({
    enabled: Boolean(latestRunTarget),
    queryFn: () =>
      getWorkflowRunDetail(
        project.projectId,
        latestRunTarget?.versionId ?? "",
        latestRunTarget?.runId ?? "",
      ),
    queryKey: latestRunTarget
      ? workflowRunDetailQueryKey(
          project.projectId,
          latestRunTarget.versionId,
          latestRunTarget.runId,
        )
      : ["project", project.projectId, "workflows", "runs", "none"],
    retry: false,
  });

  const handlePreviewImport = useCallback(() => {
    try {
      const nextPreview = previewWorkflowImportFromYaml(yamlText, SAMPLE_CATALOG, workflow);
      setPreview(nextPreview);
      setPreviewError(null);
      setTimelineEvents((events) => [
        { time: "00:00.512", label: "YAML import preview completed", state: "ok" },
        ...events.slice(0, 4),
      ]);
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "YAML 解析失败。");
      setTimelineEvents((events) => [
        { time: "00:00.512", label: "YAML import preview failed", state: "blocked" },
        ...events.slice(0, 4),
      ]);
    }
  }, [workflow, yamlText]);

  const handleApplyPreview = useCallback(() => {
    if (!preview) {
      return;
    }

    setWorkflow(preview.workflow);
    setSelectedEdgeId("");
    setSelectedNodeId((currentNodeId) =>
      preview.workflow.nodes.some((node) => node.id === currentNodeId)
        ? currentNodeId
        : (preview.workflow.nodes[0]?.id ?? ""),
    );
    setEdgeComposer(buildDefaultEdgeComposer(preview.workflow));
    setTimelineEvents((events) => [
      { time: "00:00.704", label: "Preview applied to canvas draft", state: "ok" },
      ...events.slice(0, 4),
    ]);
  }, [preview]);

  const handleExportYaml = useCallback(() => {
    setExportedYaml(exportWorkflowYaml(ensureWorkflowV2(workflow)));
    setTimelineEvents((events) => [
      { time: "00:00.881", label: "Workflow DSL exported as YAML", state: "ok" },
      ...events.slice(0, 4),
    ]);
  }, [workflow]);

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_event, node: Node) => {
      setSelectedNodeId(node.id);
      setSelectedEdgeId("");
    },
    [],
  );

  const handleEdgeClick = useCallback<EdgeMouseHandler>(
    (_event, edge) => {
      setSelectedEdgeId(edge.id);
    },
    [],
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) {
        return;
      }

      const nextWorkflow = createWorkflowEdge(workflow, {
        source: connection.source,
        target: connection.target,
        source_handle: connection.sourceHandle,
        target_handle: connection.targetHandle,
      });
      const newEdge = findNewEdge(workflow.edges, nextWorkflow.edges);

      setWorkflow(nextWorkflow);
      if (newEdge) {
        setSelectedEdgeId(getWorkflowEdgeIdentity(newEdge));
      }
    },
    [workflow],
  );

  const handleNodeDragStop = useCallback(
    (_event: unknown, node: Node) => {
      setWorkflow((currentWorkflow) => ({
        ...currentWorkflow,
        nodes: currentWorkflow.nodes.map((workflowNode) =>
          workflowNode.id === node.id
            ? {
                ...workflowNode,
                position: {
                  x: node.position.x,
                  y: node.position.y,
                },
              }
            : workflowNode,
        ),
      }));
    },
    [],
  );

  const handleNodeNameChange = useCallback(
    (name: string) => {
      setWorkflow((currentWorkflow) => renameWorkflowNode(currentWorkflow, selectedNode.id, name));
    },
    [selectedNode.id],
  );

  const handleNodeDataChange = useCallback(
    (dataPatch: Record<string, unknown>) => {
      setWorkflow((currentWorkflow) =>
        updateWorkflowNodeData(currentWorkflow, selectedNode.id, dataPatch),
      );
    },
    [selectedNode.id],
  );

  const handleAddNode = useCallback(
    (nodeType: NodeType) => {
      const nextWorkflow = createWorkflowNode(workflow, nodeType);
      const newNode = nextWorkflow.nodes.find(
        (node) => !workflow.nodes.some((existingNode) => existingNode.id === node.id),
      );

      setWorkflow(nextWorkflow);
      setSelectedEdgeId("");
      setEdgeComposer((currentComposer) => ({
        ...currentComposer,
        source: currentComposer.source || nextWorkflow.nodes[0]?.id || "",
        target: newNode?.id ?? currentComposer.target,
      }));
      if (newNode) {
        setSelectedNodeId(newNode.id);
      }
      setTimelineEvents((events) => [
        { time: "00:01.014", label: `${nodeType} node added from library`, state: "ok" },
        ...events.slice(0, 4),
      ]);
    },
    [workflow],
  );

  const handleCreateEdge = useCallback(() => {
    if (!edgeComposer.source || !edgeComposer.target) {
      setEdgeComposerError("Choose a source and target node.");
      return;
    }
    if (edgeComposer.source === edgeComposer.target) {
      setEdgeComposerError("Source and target must be different.");
      return;
    }

    const nextWorkflow = createWorkflowEdge(workflow, edgeComposer);
    const newEdge = findNewEdge(workflow.edges, nextWorkflow.edges);

    if (!newEdge) {
      setEdgeComposerError("This edge already exists.");
      return;
    }

    setWorkflow(nextWorkflow);
    setSelectedEdgeId(getWorkflowEdgeIdentity(newEdge));
    setSelectedNodeId(edgeComposer.target);
    setEdgeComposer((currentComposer) => ({ ...currentComposer, kind: "sequence" }));
    setEdgeComposerError(null);
    setTimelineEvents((events) => [
      { time: "00:01.188", label: `${edgeComposer.kind} edge created`, state: "ok" },
      ...events.slice(0, 4),
    ]);
  }, [edgeComposer, workflow]);

  const handleSelectedEdgeChange = useCallback(
    (patch: Partial<Omit<EdgeDefinition, "source" | "target">>) => {
      if (!selectedEdge) {
        return;
      }

      const nextWorkflow = updateWorkflowEdge(workflow, selectedEdgeId, patch);
      const updatedEdge =
        nextWorkflow.edges.find(
          (edge) =>
            edge.source === selectedEdge.source &&
            edge.target === selectedEdge.target &&
            (patch.kind ? edge.kind === patch.kind : getWorkflowEdgeIdentity(edge) === selectedEdgeId),
        ) ??
        nextWorkflow.edges.find(
          (edge) => edge.source === selectedEdge.source && edge.target === selectedEdge.target,
        );

      setWorkflow(nextWorkflow);
      if (updatedEdge) {
        setSelectedEdgeId(getWorkflowEdgeIdentity(updatedEdge));
      }
    },
    [selectedEdge, selectedEdgeId, workflow],
  );

  const handleSelectedEdgeKindChange = useCallback(
    (kind: EdgeKind) => {
      handleSelectedEdgeChange({
        kind,
        loop: kind === "loop" ? { max_iterations: selectedEdge?.loop?.max_iterations ?? 3 } : undefined,
        source_handle:
          kind === "condition" ? (selectedEdge?.source_handle ?? "case:default") : selectedEdge?.source_handle,
      });
    },
    [handleSelectedEdgeChange, selectedEdge],
  );

  const handleDeleteSelectedEdge = useCallback(() => {
    if (!selectedEdgeId) {
      return;
    }

    const nextWorkflow = deleteWorkflowEdge(workflow, selectedEdgeId);
    setWorkflow(nextWorkflow);
    setSelectedEdgeId("");
    setTimelineEvents((events) => [
      { time: "00:01.274", label: "Selected edge deleted", state: "ok" },
      ...events.slice(0, 4),
    ]);
  }, [selectedEdgeId, workflow]);

  const handleDeleteSelectedNode = useCallback(() => {
    if (!selectedNode) {
      return;
    }

    const nextWorkflow = deleteWorkflowNode(workflow, selectedNode.id);
    setWorkflow(nextWorkflow);
    setSelectedNodeId(nextWorkflow.nodes[0]?.id ?? "");
    setSelectedEdgeId("");
    setEdgeComposer(buildDefaultEdgeComposer(nextWorkflow));
    setTimelineEvents((events) => [
      { time: "00:01.336", label: `${selectedNode.id} node deleted`, state: "ok" },
      ...events.slice(0, 4),
    ]);
  }, [selectedNode, workflow]);

  return (
    <>
      <main className="aegis-main workflow-studio-main">
        <section className="workflow-studio-stage" aria-label="Workflow Canvas">
          <div className="workflow-stage-header">
            <div>
              <div className="telemetry">WORKFLOW STUDIO</div>
              <h2>Workflow Canvas</h2>
            </div>
            <div className="workflow-toolbar" aria-label="Workflow actions">
              <button className="toolbar-button" onClick={handlePreviewImport} type="button">
                <FileSearch aria-hidden="true" size={16} />
                预览导入
              </button>
              <button
                className="toolbar-button"
                disabled={!preview}
                onClick={handleApplyPreview}
                type="button"
              >
                <Import aria-hidden="true" size={16} />
                应用预览到画布
              </button>
              <button className="toolbar-button" onClick={handleExportYaml} type="button">
                <Download aria-hidden="true" size={16} />
                导出 YAML
              </button>
            </div>
          </div>

          <div className="workflow-stats" aria-label="Workflow summary">
            <Metric label="Nodes" value={String(workflow.nodes.length).padStart(2, "0")} />
            <Metric label="Edges" value={String(workflow.edges.length).padStart(2, "0")} />
            <Metric label="Project" value={project.projectId} />
            <Metric label="Run Gate" value={previewSummary?.canPublishOrRun ? "Ready" : "Blocked"} />
          </div>

          <NodeLibrary items={NODE_LIBRARY_ITEMS} onAddNode={handleAddNode} />

          <div className="workflow-canvas">
            <ReactFlow
              colorMode="dark"
              edges={flowEdges}
              fitView
              minZoom={0.45}
              nodes={flow.nodes}
              nodeTypes={nodeTypes}
              onConnect={handleConnect}
              onEdgeClick={handleEdgeClick}
              onNodeClick={handleNodeClick}
              onNodeDragStop={handleNodeDragStop}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#2b3b36" gap={24} />
              <MiniMap nodeColor={getMiniMapNodeColor} pannable zoomable />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        </section>
      </main>

      <aside className="aegis-inspector workflow-inspector">
        <div className="telemetry">导入预览</div>
        <h2>{workflow.workflow.name}</h2>
        <PublishPanel
          activeDraft={activeDraft}
          archiveMutationPending={archiveMutation.isPending}
          archiveReason={archiveReason}
          confirmArchiveVersionId={confirmArchiveVersionId}
          draftsError={draftsQuery.error}
          onArchive={(version) => archiveMutation.mutate(version)}
          onArchiveReasonChange={setArchiveReason}
          onCancelArchive={() => {
            setArchiveReason("");
            setConfirmArchiveVersionId("");
          }}
          onPublish={() => publishMutation.mutate()}
          onPublishCheck={() => publishCheckMutation.mutate()}
          onReleaseNoteChange={setReleaseNote}
          onRestore={(version) => restoreMutation.mutate(version)}
          onSelectVersion={setSelectedVersionId}
          onStartArchive={(version) => setConfirmArchiveVersionId(version.id)}
          publishCheckAnalysis={publishCheckAnalysis}
          publishGateResult={publishGateResult}
          publishMutationPending={publishMutation.isPending}
          publishStatus={publishStatus}
          releaseNote={releaseNote}
          restoreMutationPending={restoreMutation.isPending}
          selectedVersion={selectedVersion}
          selectedVersionId={selectedVersionId}
          versions={versions}
          versionsError={versionsQuery.error}
          workflow={workflow}
        />
        <WorkflowRunPanel
          detail={runDetailQuery.data}
          detailError={runDetailQuery.error}
          inputsError={runInputsError}
          inputsText={runInputsText}
          isDetailLoading={runDetailQuery.isLoading}
          isRunning={runMutation.isPending}
          latestRun={runMutation.data}
          onInputsTextChange={(value) => {
            setRunInputsText(value);
            setRunInputsError("");
          }}
          onRun={() => runMutation.mutate()}
          projectId={project.projectId}
          selectedVersion={selectedVersion}
        />
        <PreviewPanel error={previewError} summary={previewSummary} />

        <section className="inspector-section">
          <div className="telemetry">Edge Composer</div>
          <div className="edge-composer-grid">
            <SelectControl
              label="Edge source"
              onChange={(value) =>
                setEdgeComposer((currentComposer) => ({ ...currentComposer, source: value }))
              }
              options={nodeOptions}
              value={edgeComposer.source}
            />
            <SelectControl
              label="Edge target"
              onChange={(value) =>
                setEdgeComposer((currentComposer) => ({ ...currentComposer, target: value }))
              }
              options={nodeOptions}
              value={edgeComposer.target}
            />
            <SelectControl
              label="Edge kind"
              onChange={(value) =>
                setEdgeComposer((currentComposer) => ({
                  ...currentComposer,
                  kind: value as EdgeKind,
                }))
              }
              options={EDGE_KIND_OPTIONS}
              value={edgeComposer.kind}
            />
          </div>
          {edgeComposerError ? (
            <div className="preview-alert preview-alert-danger">{edgeComposerError}</div>
          ) : null}
          <button className="toolbar-button" onClick={handleCreateEdge} type="button">
            <Link2 aria-hidden="true" size={16} />
            Create edge
          </button>
        </section>

        <section className="inspector-section">
          <div className="telemetry">Selected Node</div>
          <SelectControl
            label="Select node for inspector"
            onChange={(value) => {
              setSelectedNodeId(value);
              setSelectedEdgeId("");
            }}
            options={nodeOptions}
            value={selectedNode.id}
          />
          <label className="field-label" htmlFor="workflow-node-name">
            节点名称
          </label>
          <input
            className="text-field"
            id="workflow-node-name"
            onChange={(event) => handleNodeNameChange(event.target.value)}
            value={selectedNode.name}
          />
          <div className="node-detail-grid">
            <DetailItem label="id" value={selectedNode.id} />
            <DetailItem label="type" value={selectedNode.type} />
            <DetailItem label="risk" value={selectedNode.risk_level ?? "low"} />
            <DetailItem label="resource" value={selectedFlowNode?.data.resourceState ?? "neutral"} />
          </div>
          <button className="toolbar-button toolbar-button-danger" onClick={handleDeleteSelectedNode} type="button">
            <Trash2 aria-hidden="true" size={16} />
            Delete selected node
          </button>
          {selectedFlowNode?.data.missingReferences.length ? (
            <div className="missing-inline">
              <ShieldAlert aria-hidden="true" size={16} />
              {selectedFlowNode.data.missingReferences.join(", ")}
            </div>
          ) : null}
        </section>

        {selectedNode.type === "llm" ? (
          <LlmControlsPanel node={selectedNode} onChange={handleNodeDataChange} />
        ) : null}

        {selectedEdge ? (
          <SelectedEdgePanel
            edge={selectedEdge}
            onChange={handleSelectedEdgeChange}
            onDelete={handleDeleteSelectedEdge}
            onKindChange={handleSelectedEdgeKindChange}
          />
        ) : null}

        <section className="inspector-section">
          <label className="field-label" htmlFor="workflow-yaml">
            Workflow YAML
          </label>
          <textarea
            className="yaml-field"
            id="workflow-yaml"
            onChange={(event) => setYamlText(event.target.value)}
            value={yamlText}
          />
        </section>

        <section className="inspector-section">
          <label className="field-label" htmlFor="workflow-exported-yaml">
            导出的 Workflow YAML
          </label>
          <textarea
            className="yaml-field yaml-field-export"
            id="workflow-exported-yaml"
            readOnly
            value={exportedYaml}
          />
        </section>
      </aside>

      <section className="aegis-timeline" aria-label="Harness Loop Timeline">
        <div className="telemetry">Harness Loop Timeline</div>
        <div className="timeline-grid">
          {selectedLlmTraceEvents.map((event) => (
            <div
              className={`timeline-row timeline-${event.status === "success" ? "ok" : "blocked"}`}
              key={`${event.nodeId}-${event.requestHash}`}
            >
              <span className="telemetry">{event.model}</span>
              <span>
                {event.status} / tokens {event.totalTokens} / {event.latencyMs}ms /{" "}
                {event.requestHash}
              </span>
            </div>
          ))}
          {timelineEvents.map((event, index) => (
            <div className={`timeline-row timeline-${event.state}`} key={`${event.time}-${event.label}-${index}`}>
              <span className="telemetry">{event.time}</span>
              <span>{event.label}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function NodeLibrary({
  items,
  onAddNode,
}: {
  items: NodeLibraryItem[];
  onAddNode: (nodeType: NodeType) => void;
}) {
  return (
    <section className="node-library" aria-label="Node library">
      <div>
        <div className="telemetry">Node Library</div>
        <strong>Harness nodes</strong>
      </div>
      <div className="node-library-actions">
        {items.map((item) => {
          const Icon = item.icon;

          return (
            <button
              aria-label={`Add ${item.label} node`}
              className="node-library-button"
              key={item.type}
              onClick={() => onAddNode(item.type)}
              type="button"
            >
              <Icon size={16} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function SelectedEdgePanel({
  edge,
  onChange,
  onDelete,
  onKindChange,
}: {
  edge: EdgeDefinition;
  onChange: (patch: Partial<Omit<EdgeDefinition, "source" | "target">>) => void;
  onDelete: () => void;
  onKindChange: (kind: EdgeKind) => void;
}) {
  const edgeKind = edge.kind ?? "sequence";

  return (
    <section className="inspector-section">
      <div className="telemetry">Selected Edge</div>
      <div className="edge-identity-row">
        <span>{edge.source}</span>
        <span>→</span>
        <span>{edge.target}</span>
      </div>
      <SelectControl
        label="Selected edge kind"
        onChange={(value) => onKindChange(value as EdgeKind)}
        options={EDGE_KIND_OPTIONS}
        value={edgeKind}
      />
      <TextControl
        label="Edge label"
        onChange={(value) => onChange({ label: value })}
        value={edge.label ?? ""}
      />
      <TextControl
        label="Source handle"
        onChange={(value) => {
          const sourceHandle = value.trim();
          onChange({ source_handle: sourceHandle ? sourceHandle : null });
        }}
        value={edge.source_handle ?? ""}
      />
      <TextControl
        label="Target handle"
        onChange={(value) => {
          const targetHandle = value.trim();
          onChange({ target_handle: targetHandle ? targetHandle : null });
        }}
        value={edge.target_handle ?? ""}
      />
      {edgeKind === "condition" ? (
        <TextControl
          label="Condition expression"
          onChange={(value) => onChange({ condition: value })}
          value={edge.condition ?? ""}
        />
      ) : null}
      {edgeKind === "loop" ? (
        <>
          <NumberControl
            label="Loop max iterations"
            min={1}
            onChange={(value) =>
              onChange({
                loop: {
                  item_path: edge.loop?.item_path,
                  max_iterations: value,
                  while_expression: edge.loop?.while_expression,
                },
              })
            }
            value={edge.loop?.max_iterations ?? 3}
          />
          <TextControl
            label="Loop while expression"
            onChange={(value) =>
              onChange({
                loop: {
                  item_path: edge.loop?.item_path,
                  max_iterations: edge.loop?.max_iterations ?? 3,
                  while_expression: value,
                },
              })
            }
            value={edge.loop?.while_expression ?? ""}
          />
        </>
      ) : null}
      <button className="toolbar-button toolbar-button-danger" onClick={onDelete} type="button">
        <Trash2 aria-hidden="true" size={16} />
        Delete selected edge
      </button>
    </section>
  );
}

function LlmControlsPanel({
  node,
  onChange,
}: {
  node: WorkflowDefinition["nodes"][number];
  onChange: (dataPatch: Record<string, unknown>) => void;
}) {
  const data = getLlmNodeData(node);

  return (
    <section className="inspector-section">
      <div className="telemetry">LLM Controls</div>
      <TextControl
        label="Model Policy Ref"
        onChange={(value) => onChange({ model_policy_ref: value })}
        value={data.model_policy_ref ?? "default"}
      />
      <TextControl
        label="Prompt Template Ref"
        onChange={(value) => onChange({ prompt_template_ref: value })}
        value={data.prompt_template_ref ?? ""}
      />
      <TextControl
        label="Prompt Version"
        onChange={(value) => onChange({ prompt_version: value })}
        value={data.prompt_version ?? ""}
      />
      <NumberControl
        label="Temperature"
        max={2}
        min={0}
        onChange={(value) => onChange({ temperature: value })}
        step={0.1}
        value={data.temperature ?? 0}
      />
      <NumberControl
        label="Max Tokens"
        min={1}
        onChange={(value) => onChange({ max_tokens: value })}
        value={data.max_tokens ?? 256}
      />
      <TextControl
        label="Output Schema Ref"
        onChange={(value) => onChange({ output_schema_ref: value })}
        value={data.output_schema_ref ?? ""}
      />
    </section>
  );
}

function PublishPanel({
  activeDraft,
  archiveMutationPending,
  archiveReason,
  confirmArchiveVersionId,
  draftsError,
  onArchive,
  onArchiveReasonChange,
  onCancelArchive,
  onPublish,
  onPublishCheck,
  onReleaseNoteChange,
  onRestore,
  onSelectVersion,
  onStartArchive,
  publishCheckAnalysis,
  publishGateResult,
  publishMutationPending,
  publishStatus,
  releaseNote,
  restoreMutationPending,
  selectedVersion,
  selectedVersionId,
  versions,
  versionsError,
  workflow,
}: {
  activeDraft: WorkflowDraftRead | null;
  archiveMutationPending: boolean;
  archiveReason: string;
  confirmArchiveVersionId: string;
  draftsError: Error | null;
  onArchive: (version: WorkflowVersionRead) => void;
  onArchiveReasonChange: (value: string) => void;
  onCancelArchive: () => void;
  onPublish: () => void;
  onPublishCheck: () => void;
  onReleaseNoteChange: (value: string) => void;
  onRestore: (version: WorkflowVersionRead) => void;
  onSelectVersion: (versionId: string) => void;
  onStartArchive: (version: WorkflowVersionRead) => void;
  publishCheckAnalysis: WorkflowImportAnalysis | null;
  publishGateResult: WorkflowPublishGateResult | null;
  publishMutationPending: boolean;
  publishStatus: PublishStatus;
  releaseNote: string;
  restoreMutationPending: boolean;
  selectedVersion: WorkflowVersionRead | null;
  selectedVersionId: string;
  versions: WorkflowVersionRead[];
  versionsError: Error | null;
  workflow: WorkflowDefinition;
}) {
  const hasPublishedRunTarget = selectedVersion?.status === "published";
  const gateReasons = publishGateResult?.reasons ?? [];
  const publishCheckMissingLabels =
    publishCheckAnalysis?.missing_references.map(
      (reference) => `${reference.reference_type}: ${reference.reference}`,
    ) ?? [];

  return (
    <section className="inspector-section workflow-release-panel" aria-label="Workflow Release">
      <div className="telemetry">Workflow Release</div>
      <div className="release-state-grid">
        <DetailItem label="draft" value={activeDraft ? `v${activeDraft.version}` : "unavailable"} />
        <DetailItem label="workflow" value={workflow.workflow.id} />
        <DetailItem label="versions" value={String(versions.length)} />
      </div>
      {draftsError ? (
        <div className="preview-alert preview-alert-danger">{getErrorMessage(draftsError)}</div>
      ) : null}
      {versionsError ? (
        <div className="preview-alert preview-alert-danger">{getErrorMessage(versionsError)}</div>
      ) : null}
      {!activeDraft ? (
        <div className="preview-alert">No active workflow draft from API; publish actions are disabled.</div>
      ) : null}
      {publishStatus.message ? (
        <div
          className={
            publishStatus.kind === "error"
              ? "preview-alert preview-alert-danger"
              : "preview-alert preview-alert-success"
          }
        >
          {publishStatus.message}
        </div>
      ) : null}
      {publishCheckMissingLabels.length ? (
        <div className="publish-gate-list">
          <strong>Publish-check references</strong>
          {publishCheckMissingLabels.map((label) => (
            <span className="publish-gate-reason publish-gate-blocker" key={label}>
              {label}
            </span>
          ))}
        </div>
      ) : null}
      {gateReasons.length ? (
        <div className="publish-gate-list">
          <strong>Gate reasons</strong>
          {gateReasons.map((reason) => (
            <div
              className={`publish-gate-reason publish-gate-${reason.severity}`}
              key={`${reason.code}-${reason.reference}-${reason.node_id}`}
            >
              <span className="telemetry">{reason.code}</span>
              <span>{reason.message}</span>
              <small>
                {reason.reference_type} {reason.reference} {reason.node_id ? `/ ${reason.node_id}` : ""}
              </small>
            </div>
          ))}
        </div>
      ) : null}
      <TextControl label="Release note" onChange={onReleaseNoteChange} value={releaseNote} />
      <div className="release-action-row">
        <button
          className="toolbar-button"
          disabled={!activeDraft}
          onClick={onPublishCheck}
          type="button"
        >
          <FileSearch aria-hidden="true" size={16} />
          发布检查
        </button>
        <button
          className="toolbar-button"
          disabled={!activeDraft || publishMutationPending}
          onClick={onPublish}
          type="button"
        >
          <ShieldCheck aria-hidden="true" size={16} />
          发布版本
        </button>
      </div>
      <div
        className={
          hasPublishedRunTarget
            ? "preview-alert preview-alert-success"
            : "preview-alert preview-alert-danger"
        }
      >
        {hasPublishedRunTarget
          ? `Run binds to version ${selectedVersion.version} / ${shortHash(selectedVersion.definition_hash)}`
          : "No published version selected for run"}
      </div>
      <div className="version-history-list" aria-label="Workflow Version History">
        <strong>Version History</strong>
        {!versions.length ? <div className="global-empty-row">No published versions yet</div> : null}
        {versions.map((version) => {
          const isSelected = version.id === selectedVersionId || selectedVersion?.id === version.id;
          const isConfirmingArchive = confirmArchiveVersionId === version.id;

          return (
            <div
              className={
                isSelected
                  ? "version-history-row version-history-row-selected"
                  : "version-history-row"
              }
              key={version.id}
            >
              <button
                className="version-history-main"
                onClick={() => onSelectVersion(version.id)}
                type="button"
              >
                <span>
                  <strong>v{version.version}</strong>
                  <small>{version.release_note || "No release note"}</small>
                </span>
                <span className={`status-pill status-version-${version.status}`}>
                  {version.status}
                </span>
              </button>
              <div className="version-history-meta">
                <span className="telemetry">{shortHash(version.definition_hash)}</span>
                <span>{formatDateTime(version.created_at)}</span>
                <span>{version.gate_result.reasons.length} gate reasons</span>
              </div>
              <div className="release-action-row">
                <button
                  className="toolbar-button"
                  disabled={restoreMutationPending}
                  onClick={() => onRestore(version)}
                  type="button"
                >
                  Restore version {version.version} as draft
                </button>
                {isConfirmingArchive ? (
                  <>
                    <TextControl
                      label="Archive reason"
                      onChange={onArchiveReasonChange}
                      value={archiveReason}
                    />
                    <button
                      className="toolbar-button toolbar-button-danger"
                      disabled={!archiveReason.trim() || archiveMutationPending}
                      onClick={() => onArchive(version)}
                      type="button"
                    >
                      Confirm archive version {version.version}
                    </button>
                    <button className="toolbar-button" onClick={onCancelArchive} type="button">
                      Cancel archive
                    </button>
                  </>
                ) : (
                  <button
                    className="toolbar-button toolbar-button-danger"
                    disabled={version.status === "archived"}
                    onClick={() => onStartArchive(version)}
                    type="button"
                  >
                    Archive version {version.version}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function WorkflowRunPanel({
  detail,
  detailError,
  inputsError,
  inputsText,
  isDetailLoading,
  isRunning,
  latestRun,
  onInputsTextChange,
  onRun,
  projectId,
  selectedVersion,
}: {
  detail: WorkflowRunDetailResponse | undefined;
  detailError: Error | null;
  inputsError: string;
  inputsText: string;
  isDetailLoading: boolean;
  isRunning: boolean;
  latestRun: WorkflowRunResult | undefined;
  onInputsTextChange: (value: string) => void;
  onRun: () => void;
  projectId: string;
  selectedVersion: WorkflowVersionRead | null;
}) {
  const canRun = selectedVersion?.status === "published";
  const status = detail?.run.status ?? latestRun?.status ?? "idle";
  const runId = detail?.run.run_id ?? latestRun?.run_id ?? "";
  const traceId = detail?.run.trace_id ?? latestRun?.trace_id ?? "";
  const versionId = selectedVersion?.id ?? latestRun?.workflow_version_id ?? "";
  const pendingApproval =
    latestRun?.pending_approval ?? readPendingApproval(detail?.run.pending_approval);
  const traceUrl = runId && traceId && versionId
    ? buildRunObservatoryUrl(projectId, versionId, runId, traceId)
    : "";

  return (
    <section className="inspector-section workflow-run-panel" aria-label="Workflow Run">
      <div className="telemetry">Workflow Run</div>
      <div className="release-state-grid">
        <DetailItem label="target" value={canRun ? `v${selectedVersion.version}` : "none"} />
        <DetailItem label="status" value={status} />
        <DetailItem label="checkpoints" value={String(detail?.checkpoints.length ?? 0)} />
      </div>
      <label className="field-label" htmlFor="workflow-run-inputs">
        Run inputs JSON
        <textarea
          aria-label="Run inputs JSON"
          className="yaml-field workflow-run-inputs"
          id="workflow-run-inputs"
          onChange={(event) => onInputsTextChange(event.target.value)}
          rows={6}
          value={inputsText}
        />
      </label>
      {inputsError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {inputsError}
        </div>
      ) : null}
      {!canRun ? (
        <div className="preview-alert preview-alert-danger">
          Select a published version before running this workflow.
        </div>
      ) : null}
      <button
        className="toolbar-button"
        disabled={!canRun || isRunning}
        onClick={onRun}
        type="button"
      >
        <GitBranch aria-hidden="true" size={16} />
        Run published version
      </button>
      {latestRun || detail ? (
        <div className="workflow-run-result">
          <div className="node-detail-grid">
            <DetailItem label="run" value={runId || "pending"} />
            <DetailItem label="trace" value={traceId || "pending"} />
            <DetailItem label="workflow" value={detail?.run.workflow_ref ?? latestRun?.workflow_ref ?? ""} />
            <DetailItem label="updated" value={formatDateTime(detail?.run.updated_at ?? latestRun?.updated_at ?? "")} />
          </div>
          <span className={`status-pill ${workflowRunStatusClass(status)}`}>{status}</span>
          {pendingApproval ? <PendingApprovalBanner approval={pendingApproval} /> : null}
          {traceUrl ? (
            <a className="toolbar-button workflow-run-link" href={traceUrl}>
              Open Run Observatory
            </a>
          ) : null}
        </div>
      ) : null}
      {isDetailLoading ? <div className="preview-alert">Loading workflow run checkpoints</div> : null}
      {detailError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {getErrorMessage(detailError)}
        </div>
      ) : null}
      {detail?.checkpoints.length ? (
        <div className="workflow-run-checkpoints">
          <strong>Checkpoint Summary</strong>
          {detail.checkpoints.map((checkpoint) => (
            <CheckpointSummary checkpoint={checkpoint} key={checkpoint.id} />
          ))}
        </div>
      ) : latestRun ? (
        <div className="preview-alert">Checkpoint summary will appear after run detail is recorded.</div>
      ) : null}
    </section>
  );
}

function PendingApprovalBanner({ approval }: { approval: WorkflowPendingApproval }) {
  return (
    <div className="preview-alert workflow-pending-approval">
      <strong>{approval.message || "Human approval required"}</strong>
      <div className="node-detail-grid">
        <DetailItem label="node" value={approval.node_id || "unknown"} />
        <DetailItem label="name" value={approval.node_name || "approval"} />
        <DetailItem label="policy" value={approval.approval_policy_ref || "unscoped"} />
        <DetailItem label="task" value={approval.approval_task_id || "pending"} />
      </div>
    </div>
  );
}

function CheckpointSummary({ checkpoint }: { checkpoint: WorkflowRunCheckpointRead }) {
  return (
    <article className="workflow-run-checkpoint">
      <div>
        <strong>{checkpoint.node_id}</strong>
        <span className="telemetry">{checkpoint.node_type}</span>
      </div>
      <span className={`status-pill ${workflowRunStatusClass(checkpoint.status)}`}>
        {checkpoint.status}
      </span>
      {checkpoint.error_message ? (
        <div className="preview-alert preview-alert-danger">{checkpoint.error_message}</div>
      ) : null}
    </article>
  );
}

function SelectControl({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  options: Array<{ label: string; value: string }>;
  value: string;
}) {
  const id = `workflow-${label.toLowerCase().replaceAll(" ", "-")}`;

  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <select
        className="text-field"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextControl({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const id = `llm-${label.toLowerCase().replaceAll(" ", "-")}`;

  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input
        className="text-field"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
  );
}

function NumberControl({
  label,
  max,
  min,
  onChange,
  step,
  value,
}: {
  label: string;
  max?: number;
  min: number;
  onChange: (value: number) => void;
  step?: number;
  value: number;
}) {
  const id = `llm-${label.toLowerCase().replaceAll(" ", "-")}`;

  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input
        className="text-field"
        id={id}
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

function buildDefaultEdgeComposer(workflow: WorkflowDefinition): EdgeComposerState {
  return {
    source: workflow.nodes[0]?.id ?? "",
    target: workflow.nodes[1]?.id ?? workflow.nodes[0]?.id ?? "",
    kind: "sequence",
  };
}

function findNewEdge(previousEdges: EdgeDefinition[], nextEdges: EdgeDefinition[]) {
  const previousEdgeIds = new Set(previousEdges.map(getWorkflowEdgeIdentity));
  return nextEdges.find((edge) => !previousEdgeIds.has(getWorkflowEdgeIdentity(edge)));
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-cell">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown workflow error";
}

function parseRunInputs(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}") as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Run inputs JSON must be an object.");
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Invalid run inputs JSON: ${error.message}`);
    }
    throw new Error("Invalid run inputs JSON.");
  }
}

function readPendingApproval(value: Record<string, unknown> | undefined): WorkflowPendingApproval | null {
  if (!value || !Object.keys(value).length) {
    return null;
  }

  return {
    approval_kind: value.approval_kind === "tool" ? "tool" : "human",
    approval_policy_ref: readString(value.approval_policy_ref),
    approval_task_id: readString(value.approval_task_id) || null,
    message: readString(value.message),
    node_id: readString(value.node_id),
    node_name: readString(value.node_name),
    payload: {},
  };
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function workflowRunStatusClass(status: WorkflowRunStatus | WorkflowNodeStatus | "idle") {
  switch (status) {
    case "success":
      return "model-trace-status-success";
    case "failed":
    case "cancelled":
      return "model-trace-status-failed";
    case "pending_approval":
    case "running":
      return "model-trace-status-pending";
    default:
      return "status-warning";
  }
}

function buildRunObservatoryUrl(
  projectId: string,
  versionId: string,
  runId: string,
  traceId: string,
) {
  const params = new URLSearchParams({
    run_id: runId,
    trace_id: traceId,
    version_id: versionId,
  });
  return `/projects/${encodeURIComponent(projectId)}/runs?${params.toString()}`;
}

function shortHash(hash: string) {
  return hash.length > 18 ? `${hash.slice(0, 18)}...` : hash;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString().replace(".000Z", "Z");
}

function PreviewPanel({
  error,
  summary,
}: {
  error: string | null;
  summary: ImportPreviewSummary | null;
}) {
  if (error) {
    return <div className="preview-alert preview-alert-danger">{error}</div>;
  }

  if (!summary) {
    return <div className="preview-alert">等待 YAML 预览</div>;
  }

  return (
    <div className="preview-panel">
      <div className="preview-status-row">
        <span className={summary.canPublishOrRun ? "status-pill status-ready" : "status-pill status-blocked"}>
          {summary.canPublishOrRun ? "允许发布/运行" : "禁止发布/运行"}
        </span>
        <span className="status-pill status-warning">缺失资源 {summary.missingCount}</span>
      </div>
      <PreviewList label="风险等级" values={summary.riskLabels} />
      <PreviewList label="Tool Groups" values={summary.toolGroups} />
      <PreviewList label="MCP Servers" values={summary.mcpServers} />
      <PreviewList label="Shell Templates" values={summary.shellTemplates} />
      <PreviewList label="Environments" values={summary.environments} />
      <PreviewList label="Missing" values={summary.missingLabels} />
      <PreviewList label="Import Diff" values={summary.diffLabels} />
    </div>
  );
}

function PreviewList({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="preview-list">
      <span className="telemetry">{label}</span>
      <div>{values.length ? values.join(", ") : "None"}</div>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function getMiniMapNodeColor(node: WorkflowFlowNode) {
  if (node.data.resourceState === "missing") {
    return "#ffb020";
  }

  if (node.data.resourceState === "ready") {
    return "#2ef3c5";
  }

  return "#6f817a";
}
