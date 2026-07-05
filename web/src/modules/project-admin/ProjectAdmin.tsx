import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  History,
  KeyRound,
  Mail,
  ShieldCheck,
  UserCog,
  UsersRound,
} from "lucide-react";
import type { ReactNode } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  getProjectAdminOverview,
  projectAdminOverviewQueryKey,
  type ProjectAdminAuditEvent,
  type ProjectAdminMemberItem,
  type ProjectAdminOverviewResponse,
  type ProjectAdminPermissionGroup,
  type ProjectAdminRoleItem,
} from "./projectAdminApi";

type ProjectAdminProps = {
  project: ProjectContext;
};

export function ProjectAdmin({ project }: ProjectAdminProps) {
  const overviewQuery = useQuery({
    queryFn: () => getProjectAdminOverview(project.projectId),
    queryKey: projectAdminOverviewQueryKey(project.projectId),
    retry: false,
    refetchInterval: 60_000,
  });
  const overview = overviewQuery.data;

  return (
    <main className="aegis-main project-admin-main">
      <section className="project-admin-hero">
        <div>
          <div className="telemetry">PROJECT ACCESS GOVERNANCE</div>
          <h2>Project Admin</h2>
          <p>
            Project-scoped member directory, role matrix, permission domains and recent access
            governance audit trail.
          </p>
        </div>
        {overview ? <ProjectAdminHeroMetrics overview={overview} /> : null}
      </section>

      {overviewQuery.isLoading ? <div className="preview-alert">Loading project admin data</div> : null}
      {overviewQuery.isError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(overviewQuery.error as Error).message}
        </div>
      ) : null}

      {overview ? (
        <section className="project-admin-grid">
          <section className="global-panel project-admin-posture-panel">
            <PanelHeader eyebrow="ACCESS POSTURE" title="Access Posture" />
            <div className="project-admin-posture-list">
              <PostureRow
                icon={<UsersRound aria-hidden="true" size={16} />}
                label="Project members"
                value={String(overview.summary.member_count)}
              />
              <PostureRow
                icon={<Activity aria-hidden="true" size={16} />}
                label="Active members"
                value={String(overview.summary.active_member_count)}
              />
              <PostureRow
                icon={<UserCog aria-hidden="true" size={16} />}
                label="Inactive members"
                value={String(overview.summary.inactive_member_count)}
              />
              <PostureRow
                icon={<History aria-hidden="true" size={16} />}
                label="Access audit events"
                value={String(overview.summary.recent_permission_event_count)}
              />
            </div>
          </section>

          <section className="global-panel project-admin-members-panel">
            <PanelHeader
              eyebrow="MEMBER DIRECTORY"
              title="Member Directory"
              count={overview.members.length}
            />
            {overview.members.length ? (
              <div className="project-admin-member-list">
                {overview.members.map((member) => (
                  <MemberRow key={member.member_id} member={member} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No members in this project</div>
            )}
          </section>

          <section className="global-panel project-admin-roles-panel">
            <PanelHeader eyebrow="ROLE MATRIX" title="Role Matrix" count={overview.roles.length} />
            {overview.roles.length ? (
              <div className="project-admin-role-list">
                {overview.roles.map((role) => (
                  <RoleRow key={role.role_id} role={role} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No roles configured</div>
            )}
          </section>

          <section className="global-panel project-admin-permissions-panel">
            <PanelHeader
              eyebrow="PERMISSION GROUPS"
              title="Permission Groups"
              count={overview.permission_groups.length}
            />
            {overview.permission_groups.length ? (
              <div className="project-admin-permission-list">
                {overview.permission_groups.map((group) => (
                  <PermissionGroupRow group={group} key={group.prefix} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No permission groups</div>
            )}
          </section>

          <section className="global-panel project-admin-audit-panel">
            <PanelHeader
              eyebrow="ACCESS CHANGE TRAIL"
              title="Access Change Trail"
              count={overview.recent_permission_events.length}
            />
            {overview.recent_permission_events.length ? (
              <div className="project-admin-audit-list">
                {overview.recent_permission_events.map((event) => (
                  <AuditEventRow event={event} key={event.event_id} />
                ))}
              </div>
            ) : (
              <div className="global-empty-row">No recent access changes</div>
            )}
          </section>
        </section>
      ) : null}
    </main>
  );
}

function ProjectAdminHeroMetrics({ overview }: { overview: ProjectAdminOverviewResponse }) {
  return (
    <div className="project-admin-hero-metrics" aria-label="Project admin metrics">
      <Metric label="Members" value={String(overview.summary.member_count)} />
      <Metric label="Roles" value={String(overview.summary.role_count)} />
      <Metric label="Permissions" value={String(overview.summary.permission_count)} />
      <Metric label="Audit" value={String(overview.summary.recent_permission_event_count)} />
    </div>
  );
}

function MemberRow({ member }: { member: ProjectAdminMemberItem }) {
  return (
    <article className="project-admin-member-row">
      <div className="project-admin-avatar" aria-hidden="true">
        {member.display_name.slice(0, 1).toUpperCase()}
      </div>
      <div>
        <strong>{member.display_name}</strong>
        <small>
          <Mail aria-hidden="true" size={13} />
          {member.email}
        </small>
      </div>
      <span className={`status-pill status-project-${member.status}`}>{member.status}</span>
      <div className="project-admin-chip-row">
        {member.role_codes.length ? (
          member.role_codes.map((roleCode) => <code key={roleCode}>{roleCode}</code>)
        ) : (
          <span className="muted-inline">No roles</span>
        )}
      </div>
    </article>
  );
}

function RoleRow({ role }: { role: ProjectAdminRoleItem }) {
  return (
    <article className="project-admin-role-row">
      <ShieldCheck aria-hidden="true" size={16} />
      <div>
        <strong>{role.code}</strong>
        <small>{role.name}</small>
        {role.description ? <p>{role.description}</p> : null}
      </div>
      <span className="status-pill">{role.member_count} active</span>
      <span className="status-pill">{role.permission_count} perms</span>
      <div className="project-admin-chip-row">
        {role.permission_codes.slice(0, 8).map((permission) => (
          <code key={permission}>{permission}</code>
        ))}
      </div>
    </article>
  );
}

function PermissionGroupRow({ group }: { group: ProjectAdminPermissionGroup }) {
  return (
    <article className="project-admin-permission-row">
      <KeyRound aria-hidden="true" size={16} />
      <div>
        <strong>{group.prefix}</strong>
        <small className="telemetry">{group.count} permission codes</small>
        <div className="project-admin-chip-row">
          {group.permission_codes.map((permission) => (
            <code key={permission}>{permission}</code>
          ))}
        </div>
      </div>
    </article>
  );
}

function AuditEventRow({ event }: { event: ProjectAdminAuditEvent }) {
  return (
    <article className="project-admin-audit-row" data-testid={`project-admin-event-${event.event_id}`}>
      <History aria-hidden="true" size={16} />
      <div>
        <strong>{event.action}</strong>
        <small className="telemetry">
          {event.target_type} / {event.target_id}
        </small>
        <p>{event.summary}</p>
      </div>
      <span className={`status-pill workflow-risk-${event.risk_level}`}>{event.risk_level}</span>
      <span className="status-pill">{event.result}</span>
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
    <div className="project-admin-posture-row">
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
