import "@xyflow/react/dist/style.css";

import { useCallback, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import { Download, FileSearch, Import, ShieldAlert } from "lucide-react";

import { SAMPLE_CATALOG, SAMPLE_WORKFLOW, SAMPLE_WORKFLOW_YAML } from "./sampleWorkflow";
import {
  buildImportPreviewSummary,
  renameWorkflowNode,
  workflowToFlow,
} from "./workflowDsl";
import { exportWorkflowYaml, previewWorkflowImportFromYaml } from "./workflowYaml";
import { WorkflowNode } from "./WorkflowNode";
import type { ProjectContext } from "../../shell/projectContext";
import type {
  ImportPreviewSummary,
  WorkflowDefinition,
  WorkflowFlowNode,
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

const nodeTypes = {
  workflowNode: WorkflowNode,
};

const initialPreview = previewWorkflowImportFromYaml(SAMPLE_WORKFLOW_YAML, SAMPLE_CATALOG);

export function WorkflowStudio({ project }: WorkflowStudioProps) {
  const [workflow, setWorkflow] = useState<WorkflowDefinition>(SAMPLE_WORKFLOW);
  const [selectedNodeId, setSelectedNodeId] = useState<string>(SAMPLE_WORKFLOW.nodes[1].id);
  const [yamlText, setYamlText] = useState(SAMPLE_WORKFLOW_YAML);
  const [preview, setPreview] = useState<WorkflowImportPreview | null>(initialPreview);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [exportedYaml, setExportedYaml] = useState("");
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([
    { time: "00:00.000", label: "Workflow DSL loaded", state: "ok" },
    { time: "00:00.146", label: "Project catalog analyzed", state: "ok" },
    { time: "00:00.318", label: "Shell template waiting for project config", state: "pending" },
  ]);

  const previewSummary = useMemo(
    () => (preview ? buildImportPreviewSummary(preview.analysis) : null),
    [preview],
  );

  const flow = useMemo(() => workflowToFlow(workflow, preview?.analysis), [preview?.analysis, workflow]);
  const selectedNode = useMemo(
    () => workflow.nodes.find((node) => node.id === selectedNodeId) ?? workflow.nodes[0],
    [selectedNodeId, workflow.nodes],
  );
  const selectedFlowNode = flow.nodes.find((node) => node.id === selectedNode.id);

  const handlePreviewImport = useCallback(() => {
    try {
      const nextPreview = previewWorkflowImportFromYaml(yamlText, SAMPLE_CATALOG);
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
  }, [yamlText]);

  const handleApplyPreview = useCallback(() => {
    if (!preview) {
      return;
    }

    setWorkflow(preview.workflow);
    setSelectedNodeId((currentNodeId) =>
      preview.workflow.nodes.some((node) => node.id === currentNodeId)
        ? currentNodeId
        : (preview.workflow.nodes[0]?.id ?? ""),
    );
    setTimelineEvents((events) => [
      { time: "00:00.704", label: "Preview applied to canvas draft", state: "ok" },
      ...events.slice(0, 4),
    ]);
  }, [preview]);

  const handleExportYaml = useCallback(() => {
    setExportedYaml(exportWorkflowYaml(workflow));
    setTimelineEvents((events) => [
      { time: "00:00.881", label: "Workflow DSL exported as YAML", state: "ok" },
      ...events.slice(0, 4),
    ]);
  }, [workflow]);

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_event, node: Node) => {
      setSelectedNodeId(node.id);
    },
    [],
  );

  const handleNodeNameChange = useCallback(
    (name: string) => {
      setWorkflow((currentWorkflow) => renameWorkflowNode(currentWorkflow, selectedNode.id, name));
    },
    [selectedNode.id],
  );

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

          <div className="workflow-canvas">
            <ReactFlow
              colorMode="dark"
              edges={flow.edges}
              fitView
              minZoom={0.45}
              nodes={flow.nodes}
              nodeTypes={nodeTypes}
              nodesDraggable={false}
              onNodeClick={handleNodeClick}
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
        <PreviewPanel error={previewError} summary={previewSummary} />

        <section className="inspector-section">
          <div className="telemetry">Selected Node</div>
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
          {selectedFlowNode?.data.missingReferences.length ? (
            <div className="missing-inline">
              <ShieldAlert aria-hidden="true" size={16} />
              {selectedFlowNode.data.missingReferences.join(", ")}
            </div>
          ) : null}
        </section>

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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-cell">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
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
