from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import (
    Account,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.iam.sqlalchemy_project_access import SqlAlchemyProjectAccessProvider
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlalchemy_project_access_provider_lists_roles_and_permissions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        account_id = uuid4()
        project_id = uuid4()
        role_id = uuid4()
        permission_id = uuid4()
        member_id = uuid4()
        session.add(Account(id=account_id, email="member@example.com", display_name="Member"))
        session.add(Project(id=project_id, slug="ops", name="Ops"))
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=account_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="ops_admin",
                name="Ops Admin",
            )
        )
        session.add(
            ProjectPermission(
                id=permission_id,
                code="tool-registry:view",
                description="View tools",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        session.add(ProjectRolePermission(role_id=role_id, permission_id=permission_id))
        await session.commit()

        provider = await SqlAlchemyProjectAccessProvider.load(session)
        principal = AccountPrincipal(account_id=account_id, status="active")

        visible_projects = provider.list_visible_projects(principal)
        project = provider.get_project_for_account(
            principal,
            project_id,
            "tool-registry:view",
        )

    await engine.dispose()

    assert [item.id for item in visible_projects] == [project_id]
    assert project is not None
    assert project.roles == ["ops_admin"]
    assert project.permissions == ["tool-registry:view"]


@pytest.mark.asyncio
async def test_sqlalchemy_project_access_provider_denies_missing_permission() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        account_id = uuid4()
        project_id = uuid4()
        member_id = uuid4()
        session.add(Account(id=account_id, email="viewer@example.com", display_name="Viewer"))
        session.add(Project(id=project_id, slug="viewer", name="Viewer"))
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=account_id))
        await session.commit()

        provider = await SqlAlchemyProjectAccessProvider.load(session)
        principal = AccountPrincipal(account_id=account_id, status="active")

        with pytest.raises(PermissionError):
            provider.get_project_for_account(
                principal,
                project_id,
                "tool-registry:view",
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_project_access_provider_ignores_role_binding_from_other_project() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        account_id = uuid4()
        project_id = uuid4()
        other_project_id = uuid4()
        member_id = uuid4()
        foreign_role_id = uuid4()
        permission_id = uuid4()
        session.add(Account(id=account_id, email="scoped@example.com", display_name="Scoped"))
        session.add(Project(id=project_id, slug="scoped", name="Scoped"))
        session.add(Project(id=other_project_id, slug="other", name="Other"))
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=account_id))
        session.add(
            ProjectRole(
                id=foreign_role_id,
                project_id=other_project_id,
                code="foreign_admin",
                name="Foreign Admin",
            )
        )
        session.add(
            ProjectPermission(
                id=permission_id,
                code="tool-registry:view",
                description="View tools",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=foreign_role_id))
        session.add(ProjectRolePermission(role_id=foreign_role_id, permission_id=permission_id))
        await session.commit()

        provider = await SqlAlchemyProjectAccessProvider.load(session)
        principal = AccountPrincipal(account_id=account_id, status="active")

        project = provider.list_visible_projects(principal)[0]
        with pytest.raises(PermissionError):
            provider.get_project_for_account(
                principal,
                project_id,
                "tool-registry:view",
            )

    await engine.dispose()

    assert project.roles == []
    assert project.permissions == []
