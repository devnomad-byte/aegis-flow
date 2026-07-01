from uuid import UUID, uuid4

import pytest
from backend.app.iam.access import (
    AccountPrincipal,
    MembershipGrant,
    PrincipalStatus,
    ProjectAccessService,
    ProjectStatus,
)


def make_principal(
    *,
    is_super_admin: bool = False,
    status: PrincipalStatus = "active",
) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=uuid4(),
        status=status,
        is_super_admin=is_super_admin,
    )


def make_grant(
    account_id: UUID,
    project_id: UUID,
    *,
    permissions: set[str],
    project_status: ProjectStatus = "active",
    member_status: PrincipalStatus = "active",
) -> MembershipGrant:
    return MembershipGrant(
        account_id=account_id,
        project_id=project_id,
        project_status=project_status,
        member_status=member_status,
        permissions=frozenset(permissions),
    )


def test_member_with_permission_can_access_project() -> None:
    account = make_principal()
    project_id = uuid4()
    service = ProjectAccessService(
        memberships=[
            make_grant(account.account_id, project_id, permissions={"project:view"}),
        ],
    )

    assert service.can_access_project(account, project_id, "project:view") is True


def test_non_member_cannot_access_project() -> None:
    account = make_principal()
    service = ProjectAccessService(memberships=[])

    assert service.can_access_project(account, uuid4(), "project:view") is False


def test_member_without_permission_cannot_access_project() -> None:
    account = make_principal()
    project_id = uuid4()
    service = ProjectAccessService(
        memberships=[
            make_grant(account.account_id, project_id, permissions={"tool:read"}),
        ],
    )

    assert service.can_access_project(account, project_id, "project:view") is False


@pytest.mark.parametrize(
    ("principal_status", "project_status", "member_status"),
    [
        ("disabled", "active", "active"),
        ("active", "archived", "active"),
        ("active", "active", "disabled"),
    ],
)
def test_inactive_principal_project_or_member_cannot_access_project(
    principal_status: PrincipalStatus,
    project_status: ProjectStatus,
    member_status: PrincipalStatus,
) -> None:
    account = make_principal(status=principal_status)
    project_id = uuid4()
    service = ProjectAccessService(
        memberships=[
            make_grant(
                account.account_id,
                project_id,
                permissions={"project:view"},
                project_status=project_status,
                member_status=member_status,
            ),
        ],
    )

    assert service.can_access_project(account, project_id, "project:view") is False


def test_super_admin_can_access_active_project_without_membership() -> None:
    account = make_principal(is_super_admin=True)
    project_id = uuid4()
    service = ProjectAccessService(active_project_ids={project_id})

    assert service.can_access_project(account, project_id, "project:view") is True


def test_super_admin_cannot_access_archived_or_unknown_project() -> None:
    account = make_principal(is_super_admin=True)
    service = ProjectAccessService(active_project_ids=set())

    assert service.can_access_project(account, uuid4(), "project:view") is False


def test_lists_visible_projects_for_account() -> None:
    account = make_principal()
    visible_project_id = uuid4()
    hidden_project_id = uuid4()
    service = ProjectAccessService(
        memberships=[
            make_grant(account.account_id, visible_project_id, permissions={"project:view"}),
            make_grant(uuid4(), hidden_project_id, permissions={"project:view"}),
        ],
    )

    assert service.list_visible_project_ids(account) == [visible_project_id]
