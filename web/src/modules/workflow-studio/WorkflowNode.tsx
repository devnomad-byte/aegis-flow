import { Handle, Position } from "@xyflow/react";

import type { WorkflowCanvasNodeData } from "./workflowTypes";

type WorkflowNodeProps = {
  data: WorkflowCanvasNodeData;
};

const riskLabel: Record<WorkflowCanvasNodeData["riskLevel"], string> = {
  low: "LOW",
  medium: "MED",
  high: "HIGH",
  critical: "CRIT",
};

const resourceLabel: Record<WorkflowCanvasNodeData["resourceState"], string> = {
  ready: "Ready",
  missing: "待配置",
  neutral: "Neutral",
};

export function WorkflowNode({ data }: WorkflowNodeProps) {
  return (
    <div className={`workflow-node workflow-node-${data.resourceState}`}>
      <Handle className="workflow-handle" position={Position.Left} type="target" />
      <div className="workflow-node-header">
        <span className="workflow-node-type">{data.nodeType}</span>
        <span className={`workflow-risk workflow-risk-${data.riskLevel}`}>{riskLabel[data.riskLevel]}</span>
      </div>
      <div className="workflow-node-name">{data.name}</div>
      <div className="workflow-node-id">{data.nodeId}</div>
      <div className={`workflow-node-resource workflow-resource-${data.resourceState}`}>
        {resourceLabel[data.resourceState]}
      </div>
      <Handle className="workflow-handle" position={Position.Right} type="source" />
    </div>
  );
}
