from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .models import DemoRequest
from .providers.codex_cli import CodexCliAgentProvider


class HarnessAdapter(Protocol):
    """Stable boundary for the Core Builder; other harnesses can implement it."""

    name: str

    async def build(
        self,
        *,
        request: DemoRequest,
        prompt: str,
        workspace: Path,
        transcript_dir: Path,
        allowed_roots: list[Path],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]: ...

    async def acceptance_check(
        self,
        *,
        prompt: str,
        workspace: Path,
        transcript_dir: Path,
        readable_roots: list[Path],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]: ...


class CodexCliHarness:
    """Codex CLI implementation of the Core Builder harness contract."""

    name = "codex_cli"

    def __init__(self, provider: CodexCliAgentProvider):
        self.provider = provider

    async def build(
        self,
        *,
        request: DemoRequest,
        prompt: str,
        workspace: Path,
        transcript_dir: Path,
        allowed_roots: list[Path],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        del request  # The complete request is serialized into the goal prompt.
        return await self.provider.run_workspace_builder(
            prompt=prompt,
            workspace=workspace,
            transcript_dir=transcript_dir,
            allowed_roots=allowed_roots,
            on_event=on_event,
        )

    async def acceptance_check(
        self,
        *,
        prompt: str,
        workspace: Path,
        transcript_dir: Path,
        readable_roots: list[Path],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Run a read-only Codex child that must execute the acceptance probe."""

        return await self.provider.run_workspace_acceptance(
            prompt=prompt,
            workspace=workspace,
            transcript_dir=transcript_dir,
            readable_roots=readable_roots,
            on_event=on_event,
        )
