from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..models import DemoRequest
from ..prompts import SYSTEM_PROMPT, build_agent_prompt
from .base import ProviderUnavailableError

AGENT_MAX_TOKENS = {
    "brief": 4096,
    "manager": 4096,
    "discovery": 4096,
    "product": 4096,
    "experience": 4096,
    "contract": 4096,
    "reviewer": 4096,
    "builder": 8192,
}


def _json_object(raw: str, provider_name: str, agent_id: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise RuntimeError(
                f"{provider_name} agent {agent_id} did not return a JSON object"
            ) from None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{provider_name} agent {agent_id} returned invalid JSON"
            ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{provider_name} agent {agent_id} returned a non-object payload")
    return parsed


@dataclass(slots=True)
class OpenAICompatibleAgentProvider:
    name: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 90.0

    async def run_agent(
        self,
        agent_id: str,
        request: DemoRequest,
        context: dict[str, Any],
        *,
        iteration: int = 0,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderUnavailableError(f"{self.name} provider is not configured")
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": AGENT_MAX_TOKENS.get(agent_id, 2048),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_agent_prompt(
                        agent_id, request, context, iteration=iteration
                    ),
                },
            ],
        }
        # DeepSeek V4 enables high-effort thinking by default. These agents need a
        # bounded JSON contract, not hidden reasoning that consumes the completion
        # budget and repeatedly ends with finish_reason=length.
        if self.name == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                last_json_error: RuntimeError | None = None
                for attempt in range(3):
                    attempt_payload = payload
                    if attempt:
                        attempt_payload = {
                            **payload,
                            "messages": [
                                payload["messages"][0],
                                {
                                    **payload["messages"][1],
                                    "content": (
                                        f'{payload["messages"][1]["content"]}\n\n'
                                        "上次返回为空或不是合法 json。请重新返回一个非空、合法的 JSON 对象。"
                                    ),
                                },
                            ],
                        }
                    response = await client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=attempt_payload,
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(
                            f"{self.name} provider returned HTTP {response.status_code}"
                        )
                    try:
                        body = response.json()
                        choice = body["choices"][0]
                        content = choice["message"]["content"]
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        raise RuntimeError(
                            f"{self.name} provider returned an invalid response"
                        ) from exc
                    if not isinstance(content, str):
                        raise RuntimeError(f"{self.name} provider returned empty content")
                    if choice.get("finish_reason") == "length":
                        last_json_error = RuntimeError(
                            f"{self.name} agent {agent_id} exceeded its output budget"
                        )
                        continue
                    try:
                        return _json_object(content, self.name, agent_id)
                    except RuntimeError as exc:
                        last_json_error = exc
                if last_json_error is not None:
                    raise last_json_error
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{self.name} provider request failed") from exc
        raise RuntimeError(f"{self.name} provider exhausted JSON retries")
