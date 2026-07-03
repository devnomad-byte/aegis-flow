from typing import Protocol

from backend.app.tool_gateway.schemas import ToolInvocationCreate, ToolInvocationRead


class ToolInvocationStore(Protocol):
    async def record_invocation(self, request: ToolInvocationCreate) -> ToolInvocationRead:
        raise NotImplementedError
