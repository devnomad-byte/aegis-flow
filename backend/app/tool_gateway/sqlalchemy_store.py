from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tool_gateway.models import ToolGatewayInvocation
from backend.app.tool_gateway.schemas import ToolInvocationCreate, ToolInvocationRead


class SqlAlchemyToolInvocationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_invocation(self, request: ToolInvocationCreate) -> ToolInvocationRead:
        invocation = ToolGatewayInvocation(**request.model_dump())
        self._session.add(invocation)
        await self._session.commit()
        await self._session.refresh(invocation)
        return ToolInvocationRead.model_validate(invocation)
