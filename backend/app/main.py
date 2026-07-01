from fastapi import FastAPI

from backend.app.api.router import api_router
from backend.app.core.settings import AppSettings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved_settings = settings or AppSettings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
    )
    app.include_router(api_router)
    return app


app = create_app()
