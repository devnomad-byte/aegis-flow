import { stringify } from "yaml";

import type { ProjectResourceCatalog, WorkflowDefinition } from "./workflowTypes";

export const SAMPLE_WORKFLOW: WorkflowDefinition = {
  schema_version: "workflow.dsl/v0.1",
  workflow: {
    id: "wf_yaml_ops_triage",
    project_id: "ops-command",
    name: "运维排障导入样例",
    version: 1,
    status: "draft",
  },
  inputs: [
    {
      key: "alert_payload",
      type: "object",
      required: true,
      description: "Alertmanager 或监控系统传入的告警上下文。",
    },
  ],
  nodes: [
    {
      id: "start_1",
      type: "start",
      name: "接收告警",
      description: "接收告警并锁定项目上下文。",
      position: { x: 72, y: 180 },
    },
    {
      id: "agent_1",
      type: "agent",
      name: "根因分析 Agent",
      description: "汇总指标、事件和日志，形成初步排障假设。",
      risk_level: "medium",
      position: { x: 340, y: 80 },
      data: {
        goal: "Diagnose alert context and choose governed evidence collection steps.",
        tool_groups: ["kubernetes-readonly"],
        autonomy_level: 1,
      },
    },
    {
      id: "tool_1",
      type: "mcp_tool",
      name: "查询 Pod 状态",
      description: "通过项目级 MCP 读取 Pod 状态和近期事件。",
      position: { x: 340, y: 290 },
      data: {
        mcp_server_ref: "cluster-observability",
        tool_group_ref: "kubernetes-readonly",
        tool_name: "kubectl_get_pods",
        environment: "staging",
      },
    },
    {
      id: "shell_1",
      type: "shell",
      name: "采集容器日志",
      description: "在 Docker 沙箱内执行受控 Shell 模板，不触碰宿主机。",
      risk_level: "high",
      position: { x: 630, y: 180 },
      data: {
        template_ref: "collect-pod-logs",
        template_version: 1,
        environment: "staging",
      },
    },
    {
      id: "llm_1",
      type: "llm",
      name: "LLM Summary",
      description: "Summarize the governed harness loop output through the project model policy.",
      risk_level: "medium",
      position: { x: 905, y: 70 },
      data: {
        model_policy_ref: "default",
        prompt_template_ref: "incident-summary",
        prompt_version: "v1",
        temperature: 0,
        max_tokens: 128,
        output_schema_ref: "incident-report/v1",
      },
    },
    {
      id: "end_1",
      type: "end",
      name: "输出诊断报告",
      description: "生成可审计的诊断摘要和下一步建议。",
      position: { x: 1180, y: 180 },
    },
  ],
  edges: [
    { source: "start_1", target: "agent_1" },
    { source: "agent_1", target: "tool_1" },
    { source: "tool_1", target: "shell_1" },
    { source: "shell_1", target: "llm_1" },
    { source: "llm_1", target: "end_1" },
  ],
  policies: {
    default_environment: "staging",
    max_runtime_seconds: 900,
    max_tool_calls: 20,
  },
};

export const SAMPLE_CATALOG: ProjectResourceCatalog = {
  toolGroups: ["kubernetes-readonly"],
  mcpServers: ["cluster-observability"],
  shellTemplates: [],
  environments: ["staging"],
};

export const SAMPLE_WORKFLOW_YAML = stringify(SAMPLE_WORKFLOW, { lineWidth: 0 });
