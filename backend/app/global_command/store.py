from typing import Protocol

from backend.app.global_command.schemas import GlobalCommandCenterResponse


class GlobalCommandCenterStore(Protocol):
    async def load_summary(self) -> GlobalCommandCenterResponse:
        raise NotImplementedError
