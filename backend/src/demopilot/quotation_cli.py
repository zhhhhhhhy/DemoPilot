"""Per-process lean Codex configuration, never edits the desktop config."""

import json
import os
import re
import tomllib
from pathlib import Path

from .providers.codex_cli import CodexCliAgentProvider


def isolation_flags(*, include_mcp=True):
    data = {}
    if include_mcp:
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
    for name in sorted(data.get("mcp_servers", {}) if include_mcp else {}):
        key = name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else json.dumps(name)
        flags.extend(["-c", f"mcp_servers.{key}.enabled=false"])
    return flags


class IsolatedCodexProvider(CodexCliAgentProvider):
    def _command_args(self, executable, args):
        return super()._command_args(executable, [*args[:-1], *isolation_flags(), args[-1]])


class IntentCodexProvider(IsolatedCodexProvider):
    """Text-only intake policy; never inherit the builder's execution tools.

    These are per-process CLI overrides. Existing authentication is reused,
    without loading the user's tool/plugin/hook configuration. ShellTool is
    the command-execution gate, including unified execution. Unknown/native
    OS reads are not claimed to be exhaustively observable.
    """

    disabled_features = (
        "shell_tool", "unified_exec", "code_mode", "code_mode_host",
        "browser_use", "browser_use_external", "computer_use", "view_image",
        "multi_agent", "multi_agent_v2", "apps", "plugins", "remote_plugin",
        "sleep_tool", "goals", "hooks", "memories", "workspace_dependencies",
        "skill_search", "skill_mcp_dependency_install", "tool_suggest",
        "artifact", "image_generation",
    )

    def _command_args(self, executable, args):
        flags = ["--ignore-user-config", "--ephemeral", "-c", "web_search=disabled", "-c", "agents.enabled=false"]
        for feature in self.disabled_features:
            flags.extend(["--disable", feature])
        return CodexCliAgentProvider._command_args(
            executable, [*args[:-1], *flags, *isolation_flags(include_mcp=False), args[-1]]
        )

    async def run_workspace_acceptance(self, **kwargs):
        from .quotation_loop import write_json

        transcript = Path(kwargs["transcript_dir"])
        receipt = dict(policy="intent-executable-tools-disabled-v1",
                       disabled_features=list(self.disabled_features),
                       ignore_user_config=True, web_search="disabled",
                       observed_tool_events=[],
                       boundary="CLI command/browser/image/agent capabilities disabled; root events checked. Not an OS read-isolation attestation.")
        write_json(transcript / "intent-policy.json", receipt)
        callback = kwargs.get("on_event")

        def observe(event):
            item_type = event.get("item_type")
            if item_type and item_type not in {"agent_message", "reasoning", "error"}:
                receipt["observed_tool_events"].append(event)
                write_json(transcript / "intent-policy.json", receipt)
                raise RuntimeError("Intent provider emitted a prohibited tool event")
            if callback:
                callback(event)

        kwargs["on_event"] = observe
        result = await super().run_workspace_acceptance(**kwargs)
        receipt["completed"] = True
        write_json(transcript / "intent-policy.json", receipt)
        return result
