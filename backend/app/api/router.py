from fastapi import APIRouter

from backend.app.api.routes.audit import router as audit_router
from backend.app.api.routes.global_command import router as global_command_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.knowledge import router as knowledge_router
from backend.app.api.routes.model_gateway import router as model_gateway_router
from backend.app.api.routes.project_command import router as project_command_router
from backend.app.api.routes.projects import router as projects_router
from backend.app.api.routes.retrieval import router as retrieval_router
from backend.app.api.routes.tool_gateway import router as tool_gateway_router
from backend.app.api.routes.tool_registry import router as tool_registry_router
from backend.app.api.routes.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(audit_router, prefix="/api/v1")
api_router.include_router(global_command_router, prefix="/api/v1")
api_router.include_router(knowledge_router, prefix="/api/v1")
api_router.include_router(model_gateway_router, prefix="/api/v1")
api_router.include_router(project_command_router, prefix="/api/v1")
api_router.include_router(projects_router, prefix="/api/v1")
api_router.include_router(retrieval_router, prefix="/api/v1")
api_router.include_router(tool_gateway_router, prefix="/api/v1")
api_router.include_router(tool_registry_router, prefix="/api/v1")
api_router.include_router(workflows_router, prefix="/api/v1")
