from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from backend.app.api.router import api_router
from backend.app.core.settings import AppSettings
from backend.app.workflow_runtime.checkpoint_lifecycle import LangGraphCheckpointLifecycleService


class WorkflowCheckpointLifecycle(Protocol):
    async def setup(self) -> None:
        raise NotImplementedError


def create_app(
    settings: AppSettings | None = None,
    *,
    checkpoint_lifecycle: WorkflowCheckpointLifecycle | None = None,
) -> FastAPI:
    resolved_settings = settings or AppSettings()
    lifespan = _build_lifespan(resolved_settings, checkpoint_lifecycle)
    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.add_exception_handler(RequestValidationError, _request_validation_exception_handler)
    app.include_router(api_router)
    return app


def _build_lifespan(
    settings: AppSettings,
    checkpoint_lifecycle: WorkflowCheckpointLifecycle | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.workflow_checkpoint_setup_on_startup:
            lifecycle = checkpoint_lifecycle or LangGraphCheckpointLifecycleService(
                settings.database
            )
            await lifecycle.setup()
        yield

    return lifespan


async def _request_validation_exception_handler(
    request: Request,
    exc: Exception,
) -> Response:
    if isinstance(exc, RequestValidationError):
        return await _validation_exception_handler(request, exc)
    return JSONResponse(status_code=422, content={"detail": "Request validation failed"})


async def _validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": _sanitize_validation_errors(exc.errors())},
    )


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    sanitized_errors: list[dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        sanitized_errors.append(
            {key: value for key, value in error.items() if key not in {"input", "ctx", "url"}}
        )
    return sanitized_errors


app = create_app()
