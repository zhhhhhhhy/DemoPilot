from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import DemoRequest
from ..prompts import SYSTEM_PROMPT, build_agent_prompt
from .base import ProviderUnavailableError


def _json_object(raw: str, agent_id: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(f"Codex CLI agent {agent_id} did not return a JSON object") from None
        try:
            value = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Codex CLI agent {agent_id} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Codex CLI agent {agent_id} returned a non-object payload")
    # `codex exec --output-schema` currently requires a closed schema.  The
    # provider therefore asks for one stable wrapper key while preserving the
    # agent-specific object inside it.  Accept direct objects too so older CLI
    # versions and recorded fixtures remain compatible.
    payload = value.get("payload")
    if isinstance(payload, str):
        return _json_object(payload, agent_id)
    if isinstance(payload, dict):
        return payload
    return value


def _final_message(jsonl: str, agent_id: str) -> str:
    """Extract the final agent message from `codex exec --json` JSONL."""

    messages: list[str] = []
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                messages.append(item["text"])
    if messages:
        return messages[-1]
    # Keep a useful fallback for CLI versions that print only the final JSON.
    return jsonl.strip()


def _schema_file() -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", prefix="demopilot-codex-", delete=False
    )
    try:
        json.dump(
            {
                "type": "object",
                "properties": {"payload": {"type": "string"}},
                "required": ["payload"],
                "additionalProperties": False,
            },
            handle,
        )
        return Path(handle.name)
    finally:
        handle.close()


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Terminate the CLI wrapper and descendants without waiting forever.

    On Windows `codex` is commonly a `.CMD` shim. Killing only the shim can
    leave the real CLI holding stdout/stderr open, so `communicate()` would
    never return after a timeout. `taskkill /T` closes the process tree and the
    bounded wait keeps a stuck child from wedging the DemoPilot run forever.
    """

    if os.name == "nt":
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except (TimeoutError, ProcessLookupError):
        pass
    try:
        await asyncio.wait_for(process.communicate(), timeout=2)
    except (BrokenPipeError, ConnectionResetError, ProcessLookupError, TimeoutError):
        if process.stdin is not None:
            process.stdin.close()


@dataclass(slots=True)
class CodexCliAgentProvider:
    """Run every DemoPilot agent through the locally authenticated Codex CLI.

    The provider only asks Codex for a structured decision. File writes stay in
    DemoPilot's existing run-scoped SandboxWorkspace, so a CLI model cannot
    bypass the deterministic pre-write hooks or the browser evidence gate.
    """

    command: str = "codex"
    model: str = ""
    timeout_seconds: float = 180.0
    cwd: Path | None = None
    _gate: asyncio.Semaphore | None = field(default=None, init=False, repr=False)

    name = "codex_cli"

    def executable(self) -> str | None:
        return shutil.which(self.command) or (
            self.command if Path(self.command).is_file() else None
        )

    def available(self) -> bool:
        return self.executable() is not None

    @staticmethod
    def _command_args(executable: str, args: list[str]) -> list[str]:
        if Path(executable).suffix.lower() in {".cmd", ".bat"}:
            command_line = subprocess.list2cmdline([executable, *args])
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
        return [executable, *args]

    async def run_agent(
        self,
        agent_id: str,
        request: DemoRequest,
        context: dict[str, Any],
        *,
        iteration: int = 0,
    ) -> dict[str, Any]:
        # A single local CLI process at a time avoids competing auth/session
        # state when the orchestrator starts Product, Experience, and Reviewer
        # together. The surrounding Agent Team remains parallel at the plan
        # level; only this external process boundary is serialized.
        if self._gate is None:
            self._gate = asyncio.Semaphore(1)
        async with self._gate:
            return await self._run_agent_once(
                agent_id, request, context, iteration=iteration
            )

    async def _run_agent_once(
        self,
        agent_id: str,
        request: DemoRequest,
        context: dict[str, Any],
        *,
        iteration: int = 0,
    ) -> dict[str, Any]:
        executable = self.executable()
        if not executable:
            raise ProviderUnavailableError(
                "Codex CLI is not available. Install @openai/codex and ensure codex is on PATH."
            )

        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "你现在通过本地 Codex CLI 作为 DemoPilot 的一个 Agent 工作。"
            "只能依据下面给出的客户输入和前序证据作答；不要调用工具、不要读写文件、"
            "不要输出思考过程。最终只返回一个符合 JSON Schema 的对象，格式必须是"
            "{\"payload\":\"...\"}；payload 的值是你本来要返回的 JSON 对象序列化后的单行字符串，"
            "不要使用 Markdown 或代码围栏。\n\n"
            + build_agent_prompt(agent_id, request, context, iteration=iteration)
        )
        schema_path = _schema_file()
        args = [
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--json",
            "--skip-git-repo-check",
            "--output-schema",
            str(schema_path),
            "-",
        ]
        if self.model:
            args[1:1] = ["--model", self.model]
        command = self._command_args(executable, args)
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self.cwd) if self.cwd else None,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")), timeout=self.timeout_seconds
            )
        except TimeoutError as exc:
            if process is not None:
                await _terminate_process_tree(process)
            raise RuntimeError(f"Codex CLI agent {agent_id} timed out") from exc
        except asyncio.CancelledError:
            if process is not None:
                await _terminate_process_tree(process)
            raise
        except OSError as exc:
            raise ProviderUnavailableError("Codex CLI could not be started") from exc
        finally:
            schema_path.unlink(missing_ok=True)

        if process.returncode != 0:
            stdout_text = stdout.decode("utf-8", errors="replace")
            cli_errors: list[str] = []
            for line in stdout_text.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
                    error_value = event.get("error")
                    nested_message = (
                        error_value.get("message") if isinstance(error_value, dict) else None
                    )
                    message = event.get("message") or nested_message
                    if isinstance(message, str):
                        cli_errors.append(message.replace("\n", " "))
            detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
            suffix = (cli_errors[-1] if cli_errors else detail[-1] if detail else "no diagnostic")[:500]
            raise RuntimeError(
                f"Codex CLI agent {agent_id} exited with code {process.returncode}: {suffix}"
            )
        message = _final_message(stdout.decode("utf-8", errors="replace"), agent_id)
        return _json_object(message, agent_id)
