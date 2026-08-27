from __future__ import annotations

import json
import re
from typing import Any

from ..models import DemoRequest
from ..prompts import SYSTEM_PROMPT, build_agent_prompt
from .base import ProviderUnavailableError


class ClaudeAgentProvider:
    """Adapter for Anthropic's official MIT-licensed Claude Agent SDK."""

    name = "claude"

    async def run_agent(
        self,
        agent_id: str,
        request: DemoRequest,
        context: dict[str, Any],
        *,
        iteration: int = 0,
    ) -> dict[str, Any]:
        try:
            from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query
        except ImportError as exc:
            raise ProviderUnavailableError(
                "Claude provider is not installed. Run: uv sync --extra claude"
            ) from exc

        prompt = build_agent_prompt(agent_id, request, context, iteration=iteration)
        options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            max_turns=1,
            disallowed_tools=[
                "Bash",
                "Read",
                "Write",
                "Edit",
                "WebFetch",
                "WebSearch",
            ],
        )
        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                chunks.extend(
                    block.text for block in message.content if isinstance(block, TextBlock)
                )
        raw = "\n".join(chunks).strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise RuntimeError(f"Claude agent {agent_id} did not return JSON")
        result = json.loads(match.group(0))
        if not isinstance(result, dict):
            raise RuntimeError(f"Claude agent {agent_id} returned an invalid payload")
        return result
