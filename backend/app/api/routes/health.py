from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.core.settings import AppSettings

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


def build_health_response(settings: AppSettings) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.app_version,
    )


@router.get("/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return build_health_response(AppSettings())


@router.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    return build_health_response(AppSettings())
