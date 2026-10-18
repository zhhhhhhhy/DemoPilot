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
    for name in sorted(data.get("mcp_servers", {})):
        key = name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else json.dumps(name)
        flags.extend(["-c", f"mcp_servers.{key}.enabled=false"])
    return flags


class IsolatedCodexProvider(CodexCliAgentProvider):
    def _command_args(self, executable, args):
        return super()._command_args(executable, [*args[:-1], *isolation_flags(), args[-1]])
