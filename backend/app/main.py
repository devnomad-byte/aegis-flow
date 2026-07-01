from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from backend.app.api.router import api_router
from backend.app.core.settings import AppSettings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved_settings = settings or AppSettings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
    )
    app.add_exception_handler(RequestValidationError, _request_validation_exception_handler)
    app.include_router(api_router)
    return app


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
