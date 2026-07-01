from fastapi import HTTPException, status

from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider


def get_current_account() -> AccountPrincipal:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def get_project_access_provider() -> ProjectAccessProvider:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Project access provider is not configured",
    )
