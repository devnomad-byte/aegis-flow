from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_global_command_center_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.global_command.schemas import GlobalCommandCenterResponse
from backend.app.global_command.store import GlobalCommandCenterStore
from backend.app.iam.access import AccountPrincipal

router = APIRouter(tags=["global-command"])
CurrentAccount = Depends(get_current_account)
AuditStore = Depends(get_audit_event_store)
GlobalCommandStore = Depends(get_global_command_center_store)


@router.get("/global/command-center", response_model=GlobalCommandCenterResponse)
async def get_global_command_center(
    current_account: AccountPrincipal = CurrentAccount,
    command_store: GlobalCommandCenterStore = GlobalCommandStore,
    audit_store: AuditEventStore = AuditStore,
) -> GlobalCommandCenterResponse:
    if not current_account.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global command center requires super admin",
        )

    summary = await command_store.load_summary()
    await audit_store.record_global_event(
        actor_id=current_account.account_id,
        action="global.command_center.view",
        target_type="global_command_center",
        target_id="global",
        result="success",
        risk_level="medium",
        metadata={
            "total_projects": summary.overview.total_projects,
            "pending_approvals": summary.risk_approval.pending_approvals,
            "high_risk_invocations": summary.risk_approval.high_risk_invocations,
            "unhealthy_mcp_servers": summary.system_health.unhealthy_mcp_servers,
        },
    )
    return summary
