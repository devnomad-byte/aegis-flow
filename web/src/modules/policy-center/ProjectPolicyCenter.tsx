import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Clock3,
  GitCompareArrows,
  KeyRound,
  Network,
  PlayCircle,
  RotateCcw,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  decideRuntimeApproval,
  getApprovalPolicyVersions,
  getPolicyCenterOverview,
  getRuntimeApprovalTasks,
  policyCenterApprovalPolicyVersionsQueryKey,
  policyCenterOverviewQueryKey,
  rollbackApprovalPolicy,
  runtimeApprovalTasksQueryKey,
  type ApprovalPolicyImpactSummary,
  type ApprovalPolicyVersion,
  type PolicyCenterOverviewResponse,
  type PolicyCenterPendingApproval,
  type PolicyCenterPolicyEvent,
  type PolicyCenterRiskSurface,
  type PolicyCenterRoleItem,
  type RuntimeApprovalDecision,
  type RuntimeApprovalTask,
} from "./policyCenterApi";

type ProjectPolicyCenterProps = {
  project: ProjectContext;
};

export function ProjectPolicyCenter({ project }: ProjectPolicyCenterProps) {
  const queryClient = useQueryClient();
  const [runtimeDecisionReason, setRuntimeDecisionReason] = useState(
    "Reviewed in Policy Center runtime approval inbox",
  );
  const overviewQuery = useQuery({
    queryFn: () => getPolicyCenterOverview(project.projectId),
    queryKey: policyCenterOverviewQueryKey(project.projectId),
    retry: false,
    refetchInterval: 60_000,
  });
  const approvalPoliciesQuery = useQuery({
    queryFn: () => getApprovalPolicyVersions(project.projectId),
    queryKey: policyCenterApprovalPolicyVersionsQueryKey(project.projectId),
    retry: false,
    refetchInterval: 60_000,
  });
  const runtimeApprovalsQuery = useQuery({
    queryFn: () => getRuntimeApprovalTasks(project.projectId, { limit: 50, status: "pending" }),
    queryKey: runtimeApprovalTasksQueryKey(project.projectId, "pending"),
    retry: false,
    refetchInterval: 30_000,
  });
  const rollbackMutation = useMutation({
    mutationFn: (version: ApprovalPolicyVersion) =>
      rollbackApprovalPolicy(project.projectId, version.policy_ref, {
        target_version: version.version,
        reason: "Rollback from Policy Center",
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: policyCenterApprovalPolicyVersionsQueryKey(project.projectId),
        }),
        queryClient.invalidateQueries({ queryKey: policyCenterOverviewQueryKey(project.projectId) }),
      ]);
    },
  });
  const runtimeDecisionMutation = useMutation({
    mutationFn: (variables: { decision: RuntimeApprovalDecision; task: RuntimeApprovalTask }) =>
      decideRuntimeApproval(project.projectId, variables.task.id, {
        decision: variables.decision,
        reason: runtimeDecisionReason.trim(),
      }),
    onSuccess: async (task) => {
      if (task.project_id !== project.projectId) {
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: runtimeApprovalTasksQueryKey(project.projectId, "pending"),
        }),
        queryClient.invalidateQueries({ queryKey: policyCenterOverviewQueryKey(project.projectId) }),
      ]);
    },
  });
  const overview = overviewQuery.data;
  const approvalPolicies = approvalPoliciesQuery.data;
  const runtimeApprovals = runtimeApprovalsQuery.data;

  return (
    <main className="aegis-main policy-center-main">
      <section className="policy-center-hero">
        <div>
          <div className="telemetry">PROJECT POLICY POSTURE</div>
          <h2>Policy Center</h2>
          <p>
            Project-scoped governance for RBAC, tool risk, model policy, shell admission, egress,
            approvals and recent Policy Gate decisions.
          </p>
        </div>
        {overview ? <PolicyHeroMetrics overview={overview} /> : null}
      </section>

      {overviewQuery.isLoading ? <div className="preview-alert">Loading policy center data</div> : null}
      {overviewQuery.isError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(overviewQuery.error as Error).message}
        </div>
      ) : null}
      {approvalPoliciesQuery.isError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(approvalPoliciesQuery.error as Error).message}
        </div>
      ) : null}
      {runtimeApprovalsQuery.isError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(runtimeApprovalsQuery.error as Error).message}
        </div>
      ) : null}
      {rollbackMutation.isError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(rollbackMutation.error as Error).message}
        </div>
      ) : null}
      {runtimeDecisionMutation.isError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(runtimeDecisionMutation.error as Error).message}
        </div>
      ) : null}

      {overview ? (
        <section className="policy-center-grid">
          <section className="global-panel policy-posture-panel">
            <PanelHeader eyebrow="POLICY POSTURE" title="Policy Posture" />
            <div className="policy-posture-list">
              <PostureRow
                icon={<ShieldCheck aria-hidden="true" size={16} />}
                label="Shell image policy"
                value={overview.summary.shell_policy_status}
              />
              <PostureRow
                icon={<AlertTriangle aria-hidden="true" size={16} />}
                label="High risk surfaces"
                value={String(overview.summary.high_risk_surface_count)}
              />
              <PostureRow
                icon={<Clock3 aria-hidden="true" size={16} />}
                label="Pending approvals"
                value={String(overview.summary.pending_approval_count)}
              />
              <PostureRow
                icon={<Network aria-hidden="true" size={16} />}
                label="Egress profiles"
                value={String(overview.summary.egress_profile_count)}
              />
            </div>
          </section>

          <section className="global-panel policy-rbac-panel">
            <PanelHeader eyebrow="RBAC MATRIX" title="RBAC Matrix" count={overview.roles.length} />
            {overview.roles.length ? (
              <div className="policy-role-list">
                {overview.roles.map((role) => (
                  <RoleRow key={role.role_id} role={role} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No roles configured</div>
            )}
            {overview.permission_groups.length ? (
              <div className="policy-permission-cloud">
                {overview.permission_groups.map((group) => (
                  <span className="status-pill" key={group.prefix} title={group.permission_codes.join(", ")}>
                    {group.prefix} {group.count}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          <section className="global-panel policy-risk-panel">
            <PanelHeader
              eyebrow="RISK SURFACES"
              title="Risk Surfaces"
              count={overview.risk_surfaces.length}
            />
            {overview.risk_surfaces.length ? (
              <div className="policy-surface-list">
                {overview.risk_surfaces.map((surface) => (
                  <RiskSurfaceRow key={`${surface.kind}:${surface.id}`} surface={surface} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No risk surfaces detected</div>
            )}
          </section>

          <section className="global-panel policy-event-panel">
            <PanelHeader
              eyebrow="RECENT POLICY DECISIONS"
              title="Recent Policy Decisions"
              count={overview.recent_policy_events.length}
            />
            {overview.recent_policy_events.length ? (
              <div className="policy-event-list">
                {overview.recent_policy_events.map((event) => (
                  <PolicyEventRow event={event} key={event.event_id} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No recent policy decisions</div>
            )}
          </section>

          <section className="global-panel policy-approval-panel">
            <PanelHeader
              eyebrow="PENDING APPROVALS"
              title="Pending Approvals"
              count={overview.pending_approvals.length}
            />
            {overview.pending_approvals.length ? (
              <div className="policy-approval-list">
                {overview.pending_approvals.map((approval) => (
                  <PendingApprovalRow approval={approval} key={approval.approval_task_id} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No pending approvals</div>
            )}
          </section>

          <section className="global-panel policy-runtime-approval-panel">
            <PanelHeader
              eyebrow="RUNTIME APPROVALS"
              title="Runtime Approval Inbox"
              count={runtimeApprovals?.count ?? 0}
            />
            <RuntimeApprovalInbox
              decisionPending={runtimeDecisionMutation.isPending}
              decisionReason={runtimeDecisionReason}
              onDecision={(task, decision) => runtimeDecisionMutation.mutate({ decision, task })}
              onReasonChange={setRuntimeDecisionReason}
              tasks={runtimeApprovals?.tasks ?? []}
            />
          </section>

          <section className="global-panel policy-editor-panel">
            <PanelHeader
              eyebrow="APPROVAL POLICY"
              title="Approval Policy"
              count={approvalPolicies?.count ?? 0}
            />
            <ApprovalPolicyPanel
              current={approvalPolicies?.current ?? null}
              versions={approvalPolicies?.versions ?? []}
              rollbackPending={rollbackMutation.isPending}
              onRollback={(version) => rollbackMutation.mutate(version)}
            />
          </section>
        </section>
      ) : null}
    </main>
  );
}

function ApprovalPolicyPanel({
  current,
  onRollback,
  rollbackPending,
  versions,
}: {
  current: ApprovalPolicyVersion | null;
  onRollback: (version: ApprovalPolicyVersion) => void;
  rollbackPending: boolean;
  versions: ApprovalPolicyVersion[];
}) {
  if (!current) {
    return (
      <div className="policy-empty-state">
        <strong>No approval policy published</strong>
        <p>High and critical tool approvals remain enforced by default</p>
      </div>
    );
  }

  const impact = current.impact_summary ?? current.validation_result?.impact_summary ?? null;
  const rollbackVersions = versions.filter((version) => version.status === "superseded");

  return (
    <div className="policy-editor-stack">
      <article className="policy-current-version">
        <div>
          <strong>{current.title}</strong>
          <small className="telemetry">
            {current.policy_ref} / v{current.version} / {current.status}
          </small>
        </div>
        <span className="status-pill">v{current.version}</span>
        <span className="status-pill">{current.rule_count} rules</span>
      </article>
      {impact ? <ApprovalPolicyImpact impact={impact} /> : null}
      <div className="policy-version-list">
        {rollbackVersions.length ? (
          rollbackVersions.slice(0, 4).map((version) => (
            <button
              className="policy-version-row"
              disabled={rollbackPending}
              key={version.id}
              onClick={() => onRollback(version)}
              type="button"
            >
              <RotateCcw aria-hidden="true" size={15} />
              <span>Rollback to v{version.version}</span>
              <small>{version.rule_count} rules</small>
            </button>
          ))
        ) : (
          <div className="global-empty-row">No previous policy versions</div>
        )}
      </div>
    </div>
  );
}

function RuntimeApprovalInbox({
  decisionPending,
  decisionReason,
  onDecision,
  onReasonChange,
  tasks,
}: {
  decisionPending: boolean;
  decisionReason: string;
  onDecision: (task: RuntimeApprovalTask, decision: RuntimeApprovalDecision) => void;
  onReasonChange: (reason: string) => void;
  tasks: RuntimeApprovalTask[];
}) {
  return (
    <div className="runtime-approval-stack">
      <label className="runtime-approval-reason">
        <span>Decision reason</span>
        <input
          aria-label="Runtime approval decision reason"
          onChange={(event) => onReasonChange(event.target.value)}
          value={decisionReason}
        />
      </label>
      {tasks.length ? (
        <div className="runtime-approval-list">
          {tasks.map((task) => (
            <RuntimeApprovalRow
              decisionDisabled={decisionPending || !decisionReason.trim() || task.status !== "pending"}
              key={task.id}
              onDecision={onDecision}
              task={task}
            />
          ))}
        </div>
      ) : (
        <div className="global-empty-row">No runtime approvals pending</div>
      )}
    </div>
  );
}

function RuntimeApprovalRow({
  decisionDisabled,
  onDecision,
  task,
}: {
  decisionDisabled: boolean;
  onDecision: (task: RuntimeApprovalTask, decision: RuntimeApprovalDecision) => void;
  task: RuntimeApprovalTask;
}) {
  const safePayload = summarizePublicPayload(task.public_payload);
  const runHref = buildRunObservatoryHref(task);

  return (
    <article className="runtime-approval-row">
      <PlayCircle aria-hidden="true" size={16} />
      <div>
        <strong>{task.target_ref}</strong>
        <small className="telemetry">
          {task.target_kind} / {task.run_id || "run n/a"} / {task.node_id || "node n/a"}
        </small>
        {safePayload ? <p>{safePayload}</p> : null}
        {runHref ? (
          <a className="runtime-approval-link" href={runHref}>
            Open Run Observatory
          </a>
        ) : null}
      </div>
      <span className={`status-pill workflow-risk-${task.risk_level}`}>{task.risk_level}</span>
      <span className="status-pill">{task.status}</span>
      <div className="runtime-approval-actions">
        <button
          className="toolbar-button"
          disabled={decisionDisabled}
          onClick={() => onDecision(task, "approved")}
          type="button"
        >
          Approve {task.target_ref}
        </button>
        <button
          className="toolbar-button"
          disabled={decisionDisabled}
          onClick={() => onDecision(task, "rejected")}
          type="button"
        >
          Reject {task.target_ref}
        </button>
        <button
          className="toolbar-button"
          disabled={decisionDisabled}
          onClick={() => onDecision(task, "revoked")}
          type="button"
        >
          Revoke {task.target_ref}
        </button>
      </div>
    </article>
  );
}

function ApprovalPolicyImpact({ impact }: { impact: ApprovalPolicyImpactSummary }) {
  return (
    <div className="policy-impact-grid">
      <PostureRow
        icon={<GitCompareArrows aria-hidden="true" size={16} />}
        label="Matched surfaces"
        value={String(impact.matched_surface_count)}
      />
      <PostureRow
        icon={<AlertTriangle aria-hidden="true" size={16} />}
        label="High risk"
        value={String(impact.high_risk_surface_count)}
      />
      <PostureRow
        icon={<ShieldCheck aria-hidden="true" size={16} />}
        label="Approval rules"
        value={String(impact.approval_rule_count)}
      />
      <PostureRow
        icon={<Network aria-hidden="true" size={16} />}
        label="Model policies"
        value={String(impact.model_policy_count)}
      />
    </div>
  );
}

function PolicyHeroMetrics({ overview }: { overview: PolicyCenterOverviewResponse }) {
  return (
    <div className="policy-hero-metrics" aria-label="Policy center metrics">
      <Metric label="Roles" value={String(overview.summary.role_count)} />
      <Metric label="Permissions" value={String(overview.summary.permission_count)} />
      <Metric label="Members" value={String(overview.summary.member_count)} />
      <Metric label="Policy events" value={String(overview.summary.recent_policy_event_count)} />
    </div>
  );
}

function RoleRow({ role }: { role: PolicyCenterRoleItem }) {
  return (
    <article className="policy-role-row">
      <UsersRound aria-hidden="true" size={16} />
      <div>
        <strong>{role.code}</strong>
        <small>{role.name}</small>
        {role.description ? <p>{role.description}</p> : null}
      </div>
      <span className="status-pill">{role.member_count} members</span>
      <span className="status-pill">{role.permission_count} perms</span>
      <div className="policy-chip-row">
        {role.permission_codes.slice(0, 6).map((permission) => (
          <code key={permission}>{permission}</code>
        ))}
      </div>
    </article>
  );
}

function RiskSurfaceRow({ surface }: { surface: PolicyCenterRiskSurface }) {
  return (
    <article className={`policy-surface-row workflow-risk-${surface.risk_level}`}>
      <KeyRound aria-hidden="true" size={16} />
      <div>
        <strong>{surface.label}</strong>
        <small className="telemetry">
          {surface.kind} / {surface.policy_ref || "unscoped"}
          {surface.environment_key ? ` / ${surface.environment_key}` : ""}
        </small>
        {surface.summary ? <p>{surface.summary}</p> : null}
      </div>
      <span className={`status-pill workflow-risk-${surface.risk_level}`}>{surface.risk_level}</span>
      <span className="status-pill">{surface.status}</span>
    </article>
  );
}

function PolicyEventRow({ event }: { event: PolicyCenterPolicyEvent }) {
  return (
    <article className="policy-event-row" data-testid={`policy-center-event-${event.event_ref}`}>
      <div>
        <strong>{event.target_ref || event.target_type || event.event_ref}</strong>
        <small className="telemetry">
          {event.gate_ref || "policy_gate"} / {event.policy_ref || "unscoped"} /{" "}
          {event.run_id || "run n/a"}
        </small>
        {event.reason_summary ? <p>{event.reason_summary}</p> : null}
      </div>
      <span className={`status-pill workflow-risk-${event.risk_level}`}>{event.risk_level}</span>
      <span className="status-pill">{event.decision}</span>
      <strong>{event.duration_ms}ms</strong>
    </article>
  );
}

function PendingApprovalRow({ approval }: { approval: PolicyCenterPendingApproval }) {
  return (
    <article className="policy-approval-row">
      <Clock3 aria-hidden="true" size={16} />
      <div>
        <strong>{approval.tool_ref}</strong>
        <small className="telemetry">
          {approval.server_ref} / {approval.run_id || "run n/a"} / {approval.node_id || "node n/a"}
        </small>
      </div>
      <span className={`status-pill workflow-risk-${approval.effective_risk_level}`}>
        {approval.effective_risk_level}
      </span>
      <span className="status-pill">{approval.status}</span>
    </article>
  );
}

function summarizePublicPayload(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload).filter(([, value]) => {
    const valueType = typeof value;
    return value === null || ["string", "number", "boolean"].includes(valueType);
  });
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" / ");
}

function buildRunObservatoryHref(task: RuntimeApprovalTask): string {
  if (!task.run_id && !task.trace_id) {
    return "";
  }
  const params = new URLSearchParams();
  if (task.run_id) {
    params.set("run_id", task.run_id);
  }
  if (task.trace_id) {
    params.set("trace_id", task.trace_id);
  }
  if (task.node_id) {
    params.set("node_id", task.node_id);
  }
  return `/projects/${encodeURIComponent(task.project_id)}/runs?${params.toString()}`;
}

function PostureRow({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="policy-posture-row">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PanelHeader({
  count,
  eyebrow,
  title,
}: {
  count?: number;
  eyebrow: string;
  title: string;
}) {
  return (
    <div className="global-panel-header">
      <div>
        <div className="telemetry">{eyebrow}</div>
        <h3>{title}</h3>
      </div>
      {typeof count === "number" ? <span className="global-panel-count">{count}</span> : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="template-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
