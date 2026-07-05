from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.model_gateway.models import ModelGatewayPolicy
from backend.app.policy_center.schemas import ApprovalPolicyDraftCreateRequest
from backend.app.policy_center.sqlalchemy_store import (
    ApprovalPolicyValidationFailed,
    SqlAlchemyPolicyCenterStore,
)
from backend.app.tool_registry.models import ToolRegistryShellImagePolicy, ToolRegistryToolGroup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_approval_policy_publish_and_rollback_use_project_scoped_impact() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    actor_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    async with session_factory() as session:
        seed_policy_surfaces(session, actor_id, project_id, other_project_id)
        await session.commit()

        store = SqlAlchemyPolicyCenterStore(session)
        draft = await store.create_approval_policy_draft(
            project_id=project_id,
            actor_id=actor_id,
            request=ApprovalPolicyDraftCreateRequest(
                policy_ref="default",
                title="Production approval policy",
                description="Project scoped approval policy",
                rules=[
                    {
                        "rule_id": "critical-tools",
                        "title": "Critical tools require approval",
                        "target_kind": "tool_invocation",
                        "action": "require_approval",
                        "risk_levels": ["high", "critical"],
                        "match": {"tool_group_refs": ["k8s.admin"]},
                        "approver_role_refs": ["ops_admin"],
                        "reason": "production destructive action",
                    },
                    {
                        "rule_id": "shell-images",
                        "title": "Shell execution requires approval",
                        "target_kind": "shell_execution",
                        "action": "require_approval",
                        "risk_levels": ["high"],
                        "match": {},
                        "approver_role_refs": ["ops_admin"],
                        "reason": "containerized shell action",
                    },
                    {
                        "rule_id": "model-budget",
                        "title": "Model calls require approval",
                        "target_kind": "model_invocation",
                        "action": "require_approval",
                        "risk_levels": ["medium"],
                        "match": {"model_policy_refs": ["default"]},
                        "approver_role_refs": ["ops_admin"],
                        "reason": "budgeted model call",
                    },
                ],
            ),
        )

        validation = await store.validate_approval_policy_draft(
            project_id=project_id,
            draft_id=draft.id,
        )
        assert validation.valid is True
        assert validation.impact_summary.matched_surface_count == 3
        assert validation.impact_summary.high_risk_surface_count == 2
        assert validation.impact_summary.model_policy_count == 1
        assert validation.impact_summary.tool_surface_count == 1
        assert validation.impact_summary.shell_surface_count == 1

        published = await store.publish_approval_policy_draft(
            project_id=project_id,
            draft_id=draft.id,
            actor_id=actor_id,
        )
        assert published.status == "published"
        assert published.version == 1

        replacement = await store.create_approval_policy_draft(
            project_id=project_id,
            actor_id=actor_id,
            request=ApprovalPolicyDraftCreateRequest(
                policy_ref="default",
                title="Deny model policy",
                rules=[
                    {
                        "rule_id": "model-deny",
                        "title": "Deny model calls",
                        "target_kind": "model_invocation",
                        "action": "deny",
                        "risk_levels": ["medium"],
                        "match": {"model_policy_refs": ["default"]},
                        "reason": "temporary freeze",
                    }
                ],
            ),
        )
        replacement_published = await store.publish_approval_policy_draft(
            project_id=project_id,
            draft_id=replacement.id,
            actor_id=actor_id,
        )
        assert replacement_published.version == 2

        rollback = await store.rollback_approval_policy(
            project_id=project_id,
            policy_ref="default",
            target_version=1,
            actor_id=actor_id,
        )

        versions = await store.list_approval_policy_versions(project_id=project_id)
        other_versions = await store.list_approval_policy_versions(project_id=other_project_id)

    await engine.dispose()

    assert rollback.status == "published"
    assert rollback.version == 3
    assert rollback.rules[0].rule_id == "critical-tools"
    assert [version.status for version in versions] == ["published", "superseded", "superseded"]
    assert {version.version for version in versions} == {1, 2, 3}
    assert other_versions == []


@pytest.mark.asyncio
async def test_approval_policy_validation_blocks_high_risk_allow_rules() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    actor_id = uuid4()
    project_id = uuid4()
    async with session_factory() as session:
        seed_policy_surfaces(session, actor_id, project_id, uuid4())
        await session.commit()

        store = SqlAlchemyPolicyCenterStore(session)
        draft = await store.create_approval_policy_draft(
            project_id=project_id,
            actor_id=actor_id,
            request=ApprovalPolicyDraftCreateRequest(
                policy_ref="default",
                title="Unsafe allow rule",
                rules=[
                    {
                        "rule_id": "allow-critical",
                        "title": "Allow critical tools",
                        "target_kind": "tool_invocation",
                        "action": "allow",
                        "risk_levels": ["critical"],
                        "match": {"tool_group_refs": ["k8s.admin"]},
                        "reason": "should be blocked",
                    }
                ],
            ),
        )

        validation = await store.validate_approval_policy_draft(
            project_id=project_id,
            draft_id=draft.id,
        )
        assert validation.valid is False
        assert validation.blocking_issues[0].code == "high_risk_approval_floor"

        with pytest.raises(ApprovalPolicyValidationFailed):
            await store.publish_approval_policy_draft(
                project_id=project_id,
                draft_id=draft.id,
                actor_id=actor_id,
            )

    await engine.dispose()


def seed_policy_surfaces(
    session: AsyncSession,
    actor_id: UUID,
    project_id: UUID,
    other_project_id: UUID,
) -> None:
    now = datetime.now(UTC)
    session.add_all(
        [
            Account(
                id=actor_id,
                email=f"approval-policy-{actor_id.hex[:12]}@example.com",
                display_name="Approval Policy Tester",
            ),
            Project(id=project_id, slug=f"policy-{project_id.hex[:8]}", name="Policy Project"),
            Project(
                id=other_project_id,
                slug=f"policy-other-{other_project_id.hex[:8]}",
                name="Policy Other Project",
            ),
            ToolRegistryToolGroup(
                project_id=project_id,
                group_ref="k8s.admin",
                name="Kubernetes Admin",
                risk_level="critical",
                environment_key="prod",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            ),
            ToolRegistryToolGroup(
                project_id=other_project_id,
                group_ref="crm.admin",
                name="CRM Admin",
                risk_level="critical",
                environment_key="prod",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            ),
            ToolRegistryShellImagePolicy(
                project_id=project_id,
                enforcement_mode="enforced",
                cosign_required=True,
                notation_enabled=True,
                blocked_severities=["high", "critical"],
                created_by=actor_id,
                updated_by=actor_id,
            ),
            ModelGatewayPolicy(
                project_id=project_id,
                policy_ref="default",
                provider="openai-compatible",
                model_name="gpt-5.5",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
                updated_at=now,
            ),
        ]
    )
