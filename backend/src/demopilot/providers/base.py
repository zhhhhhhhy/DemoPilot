from __future__ import annotations

from typing import Any, Protocol

from ..models import DemoRequest


class ProviderUnavailableError(RuntimeError):
    pass


class AgentProvider(Protocol):
    name: str

    async def run_agent(
        self,
        agent_id: str,
        request: DemoRequest,
        context: dict[str, Any],
        *,
        iteration: int = 0,
    ) -> dict[str, Any]: ...
