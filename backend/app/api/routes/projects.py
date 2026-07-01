from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.app.api.dependencies import get_current_account, get_project_access_provider
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary

router = APIRouter(tags=["projects"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]


@router.get("/me/projects", response_model=ProjectListResponse)
def list_my_projects(
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
) -> ProjectListResponse:
    return ProjectListResponse(projects=project_access.list_visible_projects(current_account))


@router.get("/projects/{project_id}", response_model=ProjectSummary)
def get_project(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
) -> ProjectSummary:
    try:
        project = project_access.get_project_for_account(
            current_account,
            project_id,
            "project:view",
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required project permission",
        ) from exc

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    return project
