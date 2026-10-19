"""Per-process lean Codex configuration, never edits the desktop config."""

import json
import os
import re
import tomllib
from pathlib import Path

from .providers.codex_cli import CodexCliAgentProvider


def isolation_flags():
    task_codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    path = task_codex_home / "config.toml"
    data = tomllib.loads(path.read_text("utf-8")) if path.exists() else {}
    flags = ["--disable", "plugins", "--disable", "remote_plugin"]
    # Use the same official ChatGPT service and existing local authentication,
    # but avoid the observed proxy/WebSocket TLS failure and fallback delay.
    # Built-in provider IDs are reserved in CLI0.160: use a named transport.
    flags.extend([
        "-c", "model_provider=demopilot_http",
        "-c", "model_providers.demopilot_http.name=OpenAI",
        "-c", "model_providers.demopilot_http.base_url=https://chatgpt.com/backend-api/codex",
        "-c", "model_providers.demopilot_http.requires_openai_auth=true",
        "-c", "model_providers.demopilot_http.supports_websockets=false",
        "-c", "model_providers.demopilot_http.wire_api=responses",
    ])
    for name in sorted(data.get("mcp_servers", {})):
        key = name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else json.dumps(name)
        flags.extend(["-c", f"mcp_servers.{key}.enabled=false"])
    return flags


class IsolatedCodexProvider(CodexCliAgentProvider):
    def _command_args(self, executable, args):
        return super()._command_args(executable, [*args[:-1], *isolation_flags(), args[-1]])
