import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Clock3,
  KeyRound,
  Network,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import type { ReactNode } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  getPolicyCenterOverview,
  policyCenterOverviewQueryKey,
  type PolicyCenterOverviewResponse,
  type PolicyCenterPendingApproval,
  type PolicyCenterPolicyEvent,
  type PolicyCenterRiskSurface,
  type PolicyCenterRoleItem,
} from "./policyCenterApi";

type ProjectPolicyCenterProps = {
  project: ProjectContext;
};

export function ProjectPolicyCenter({ project }: ProjectPolicyCenterProps) {
  const overviewQuery = useQuery({
    queryFn: () => getPolicyCenterOverview(project.projectId),
    queryKey: policyCenterOverviewQueryKey(project.projectId),
    retry: false,
    refetchInterval: 60_000,
  });
  const overview = overviewQuery.data;

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
        </section>
      ) : null}
    </main>
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
