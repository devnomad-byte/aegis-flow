# 御流 AegisFlow

> Agent Harness Platform for governed, observable, multi-project AI workflow execution.

御流 AegisFlow is an internal platform for building and operating governed agent workflows across multiple projects. It combines workflow orchestration, agent tool use, MCP governance, policy enforcement, traceability, and controlled execution into one platform.

## Positioning

AegisFlow is not just another agent builder. It is an **Agent Harness Platform**: agents can plan and act, but every action is constrained by project boundaries, tool gateways, policies, approvals, budgets, traces, audits, and recovery flows.

Chinese positioning:

> 面向内部多项目团队的可控智能体工作流编排平台。

## Core Concept

### Agent Harness Loop

The core loop of AegisFlow:

```text
Intent
  -> Plan
  -> Policy Gate
  -> Tool / MCP / Shell Action
  -> Observation
  -> Trace & Audit
  -> Reflection
  -> Human Approval / Recovery
  -> Memory
  -> Next Action
```

中文概念：**智能体驾驭闭环 / 御流闭环**。

## Key Capabilities

- Multi-project workspace and project-level isolation
- Workflow Canvas for visual orchestration
- Agent Node for controlled autonomous tool use
- MCP Server and Tool Group governance
- Tool Gateway and Execution Gateway
- Policy Engine for RBAC, risk, approval, and runtime budgets
- Docker-isolated Shell Runner for controlled script execution
- Run history, trace timeline, audit logs, and replay
- Debug Chat for run-level diagnosis and recovery
- Global governance dashboard and project command center

## Architecture Direction

Current technical direction:

- Backend: Python, FastAPI, SQLAlchemy, Alembic
- Runtime: LangGraph-based workflow and agent orchestration
- Frontend: React, TypeScript, Vite, React Flow, TanStack Query/Router, Zustand
- Infrastructure: PostgreSQL, Redis, S3-compatible storage, Milvus

## Status

This repository is being initialized. The first implementation target is the foundation for the control plane, project isolation, and workflow runtime.
