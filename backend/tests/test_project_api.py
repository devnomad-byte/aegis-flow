from collections.abc import Iterable
from uuid import UUID, uuid4

from backend.app.api.dependencies import get_current_account, get_project_access_provider
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from fastapi.testclient import TestClient


class StubProjectAccessProvider(ProjectAccessProvider):
    def __init__(
        self,
        visible_projects: Iterable[ProjectSummary],
        detail_projects: dict[UUID, ProjectSummary],
        denied_projects: set[UUID] | None = None,
    ) -> None:
        self._visible_projects = list(visible_projects)
        self._detail_projects = detail_projects
        self._denied_projects = denied_projects or set()

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return self._visible_projects

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        if project_id in self._denied_projects:
            raise PermissionError(required_permission)
        return self._detail_projects.get(project_id)


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    return TestClient(app)


def make_account() -> AccountPrincipal:
    return AccountPrincipal(account_id=uuid4(), status="active")


def make_project(project_id: UUID | None = None, *, name: str = "运维排障项目") -> ProjectSummary:
    resolved_id = project_id or uuid4()
    return ProjectSummary(
        id=resolved_id,
        slug="ops-command",
        name=name,
        status="active",
        roles=["project_admin"],
        permissions=["project:view", "tool:read"],
    )


def test_me_projects_returns_only_projects_visible_to_current_account() -> None:
    project = make_project()
    client = build_client(
        account=make_account(),
        provider=StubProjectAccessProvider(
            visible_projects=[project],
            detail_projects={project.id: project},
        ),
    )

    response = client.get("/api/v1/me/projects")

    assert response.status_code == 200
    assert response.json() == {"projects": [project.model_dump(mode="json")]}


def test_project_detail_returns_project_when_account_has_view_permission() -> None:
    project = make_project()
    client = build_client(
        account=make_account(),
        provider=StubProjectAccessProvider(
            visible_projects=[project],
            detail_projects={project.id: project},
        ),
    )

    response = client.get(f"/api/v1/projects/{project.id}")

    assert response.status_code == 200
    assert response.json() == project.model_dump(mode="json")


def test_project_detail_hides_cross_project_access() -> None:
    project = make_project()
    client = build_client(
        account=make_account(),
        provider=StubProjectAccessProvider(
            visible_projects=[],
            detail_projects={},
        ),
    )

    response = client.get(f"/api/v1/projects/{project.id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


def test_project_detail_returns_forbidden_when_member_lacks_view_permission() -> None:
    project = make_project()
    client = build_client(
        account=make_account(),
        provider=StubProjectAccessProvider(
            visible_projects=[project],
            detail_projects={project.id: project},
            denied_projects={project.id},
        ),
    )

    response = client.get(f"/api/v1/projects/{project.id}")

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}
