from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import DemoRequest
from ..prompts import SYSTEM_PROMPT, build_agent_prompt
from .base import ProviderUnavailableError


class WorkspaceProcessTimeout(RuntimeError):
    def __init__(self, message: str, *, stdout_path: Path, stderr_path: Path):
        super().__init__(message)
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path


def _json_object(raw: str, agent_id: str) -> dict[str, Any]:
    raw = raw.strip()
    value: object | None = None
    # ``agent_message`` may contain a fenced JSON object or a short sentence
    # after the object even when --output-schema was requested. Decode the
    # first complete JSON value instead of slicing through the final brace;
    # this also handles large nested payloads safely.
    decoder = json.JSONDecoder()
    start = raw.find("{")
    if start >= 0:
        try:
            value, _ = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            value = None
    if value is None:
        raise RuntimeError(
            f"Codex CLI agent {agent_id} did not return a valid JSON object"
        )
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
                "properties": {
                    "payload": {"type": "string"}
                },
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
    reasoning_effort: str = "medium"
    timeout_seconds: float = 300.0
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
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        # A single local CLI process at a time avoids competing auth/session
        # state when the orchestrator starts Product, Experience, and Reviewer
        # together. The surrounding Agent Team remains parallel at the plan
        # level; only this external process boundary is serialized.
        if self._gate is None:
            self._gate = asyncio.Semaphore(1)
        async with self._gate:
            return await self._run_agent_once(
                agent_id, request, context, iteration=iteration, on_event=on_event
            )

    async def run_workspace_builder(
        self,
        *,
        prompt: str,
        workspace: Path,
        transcript_dir: Path,
        allowed_roots: list[Path],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Run a real file-editing Core Builder in an isolated workspace.

        The normal AgentProvider path is intentionally read-only and returns a
        JSON object. Core generation needs the CLI to edit files, so it uses a
        separate adapter boundary with an explicit ``workspace-write`` policy,
        a run-scoped ``--cd`` root, and additional writable roots limited to
        card/card-web/testdata. Raw stdout/stderr and the exact prompt are
        persisted by the caller for replayable evidence.
        """

        return await self._run_workspace_cli(
            prompt=prompt,
            workspace=workspace,
            transcript_dir=transcript_dir,
            allowed_roots=allowed_roots,
            sandbox="workspace-write",
            mode="workspace-write",
            multi_agent=True,
            purpose="Core Builder",
            on_event=on_event,
        )

    async def run_workspace_acceptance(
        self,
        *,
        prompt: str,
        workspace: Path,
        transcript_dir: Path,
        readable_roots: list[Path],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Run the read-only acceptance child used when native spawning is absent.

        This is deliberately a second real Codex CLI process, rather than a
        Python self-check in the parent. It can inspect the current card and
        must execute ``core_acceptance_cli.py``; the parser records the actual
        command-execution event and its exit code. The process has no write
        permission and cannot publish artifacts.
        """

        return await self._run_workspace_cli(
            prompt=prompt,
            workspace=workspace,
            transcript_dir=transcript_dir,
            allowed_roots=readable_roots,
            sandbox="read-only",
            mode="acceptance-child-read-only",
            multi_agent=False,
            purpose="Core Builder acceptance child",
            on_event=on_event,
        )

    async def _run_workspace_cli(
        self,
        *,
        prompt: str,
        workspace: Path,
        transcript_dir: Path,
        allowed_roots: list[Path],
        sandbox: str,
        mode: str,
        multi_agent: bool,
        purpose: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        executable = self.executable()
        if not executable:
            raise ProviderUnavailableError(
                "Codex CLI is not available. Install @openai/codex and ensure codex is on PATH."
            )
        workspace = workspace.resolve()
        transcript_dir = transcript_dir.resolve()
        transcript_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = transcript_dir / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        args = [
            "exec",
            "--sandbox",
            sandbox,
            "--ignore-rules",
            "-c",
            "approval_policy=never",
            "--cd",
            str(workspace),
            "--disable",
            "apps",
            "--color",
            "never",
            "--json",
            "--skip-git-repo-check",
        ]
        if multi_agent:
            args[8:8] = [
                "--enable",
                "multi_agent",
                "-c",
                "agents.enabled=true",
                "-c",
                "agents.max_concurrent_threads_per_session=2",
            ]
        if self.model:
            args[1:1] = ["--model", self.model]
        if self.reasoning_effort:
            args[1:1] = ["-c", f"model_reasoning_effort={self.reasoning_effort}"]
        for root in allowed_roots:
            args.extend(["--add-dir", str(root.resolve())])
        args.append("-")
        command = self._command_args(executable, args)
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workspace),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await self._communicate_workspace_process(
                process,
                prompt.encode("utf-8"),
                on_event or (lambda _event: None),
                transcript_dir / "stdout.jsonl",
                transcript_dir / "stderr.log",
                mode=mode,
            )
        except TimeoutError as exc:
            if process is not None:
                await _terminate_process_tree(process)
            if on_event:
                on_event({"type": "process.timeout", "mode": mode})
            raise WorkspaceProcessTimeout(
                f"Codex CLI {purpose} timed out",
                stdout_path=transcript_dir / "stdout.jsonl",
                stderr_path=transcript_dir / "stderr.log",
            ) from exc
        except asyncio.CancelledError:
            if process is not None:
                await _terminate_process_tree(process)
            if on_event:
                on_event({"type": "process.cancelled", "mode": mode})
            raise
        except OSError as exc:
            raise ProviderUnavailableError(f"Codex CLI {purpose} could not be started") from exc

        stdout_path = transcript_dir / "stdout.jsonl"
        stderr_path = transcript_dir / "stderr.log"
        if not stdout_path.exists():
            stdout_path.write_bytes(stdout)
        if not stderr_path.exists():
            stderr_path.write_bytes(stderr)
        parsed = self._parse_workspace_events(stdout.decode("utf-8", errors="replace"))
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise RuntimeError(
                f"Codex CLI {purpose} exited with code {process.returncode}: "
                f"{(detail[-1] if detail else 'no diagnostic')[:500]}"
            )
        return {
            "returncode": process.returncode,
            "thread_id": parsed["thread_id"],
            "event_count": len(parsed["events"]),
            "subagent_event_count": parsed["subagent_event_count"],
            "subagent_spawn_count": parsed["subagent_spawn_count"],
            "acceptance_command_passed": parsed["acceptance_command_passed"],
            "transcript": {
                "prompt": str(prompt_path),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            },
            "events": parsed["events"],
        }

    @staticmethod
    def _parse_workspace_events(jsonl: str) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        thread_id: str | None = None
        subagent_event_count = 0
        subagent_spawn_count = 0
        acceptance_command_passed = False
        for line in jsonl.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type", ""))
            if isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
            item = event.get("item")
            if isinstance(item, dict):
                item_type = str(item.get("type", ""))
                tool_name = str(item.get("tool", ""))
                if "agent" in item_type.lower() or "collab" in item_type.lower() or "collab" in event_type.lower() or "spawn" in event_type.lower():
                    subagent_event_count += 1
                if item_type == "collab_tool_call" and tool_name in {"spawn_agent", "spawn_agents", "delegate"}:
                    subagent_spawn_count += 1
                command = str(item.get("command", ""))
                if item_type == "command_execution" and "core_acceptance_cli.py" in command:
                    if str(item.get("exit_code")) == "0" and item.get("status") == "completed":
                        acceptance_command_passed = True
            events.append({"type": event_type, "item_type": item.get("type") if isinstance(item, dict) else None})
        return {
            "thread_id": thread_id,
            "events": events,
            "subagent_event_count": subagent_event_count,
            "subagent_spawn_count": subagent_spawn_count,
            "acceptance_command_passed": acceptance_command_passed,
        }

    async def _communicate_workspace_process(
        self,
        process: asyncio.subprocess.Process,
        prompt: bytes,
        on_event: Callable[[dict[str, Any]], None],
        stdout_path: Path,
        stderr_path: Path,
        *,
        mode: str = "workspace-write",
    ) -> tuple[bytes, bytes]:
        """Stream a workspace run while retaining partial output on timeout."""

        started = asyncio.get_running_loop().time()
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        pending = bytearray()
        stdout_path.write_bytes(b"")
        stderr_path.write_bytes(b"")
        on_event({"type": "process.started", "pid": process.pid, "mode": mode})

        async def read_stream(stream: asyncio.StreamReader | None, *, is_stdout: bool) -> None:
            if stream is None:
                return
            destination = stdout_path if is_stdout else stderr_path
            buffer = stdout_buffer if is_stdout else stderr_buffer
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                with destination.open("ab") as handle:
                    handle.write(chunk)
                if is_stdout:
                    pending.extend(chunk)
                    while b"\n" in pending:
                        raw_line, _, remainder = pending.partition(b"\n")
                        pending[:] = remainder
                        self._emit_jsonl_event(raw_line, on_event, started, len(buffer))
            if is_stdout and pending:
                self._emit_jsonl_event(bytes(pending), on_event, started, len(buffer))

        if process.stdin is not None:
            process.stdin.write(prompt)
            await process.stdin.drain()
            process.stdin.close()
        stdout_task = asyncio.create_task(read_stream(process.stdout, is_stdout=True))
        stderr_task = asyncio.create_task(read_stream(process.stderr, is_stdout=False))
        try:
            await asyncio.wait_for(process.wait(), timeout=self.timeout_seconds)
            await asyncio.gather(stdout_task, stderr_task)
        except TimeoutError:
            await _terminate_process_tree(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            on_event({"type": "process.timeout", "stdout_bytes": len(stdout_buffer), "elapsed_seconds": round(asyncio.get_running_loop().time() - started, 1)})
            raise
        except BaseException:
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        on_event({"type": "process.exited", "returncode": process.returncode, "stdout_bytes": len(stdout_buffer), "elapsed_seconds": round(asyncio.get_running_loop().time() - started, 1)})
        return bytes(stdout_buffer), bytes(stderr_buffer)

    async def _run_agent_once(
        self,
        agent_id: str,
        request: DemoRequest,
        context: dict[str, Any],
        *,
        iteration: int = 0,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        executable = self.executable()
        if not executable:
            raise ProviderUnavailableError(
                "Codex CLI is not available. Install @openai/codex and ensure codex is on PATH."
            )

        direct_builder = agent_id == "builder" and request.evaluation_mode == "core_generation"
        output_instruction = (
            "最终只返回本职责要求的直接 JSON 对象，不要使用 Markdown 或代码围栏。\n\n"
            if direct_builder
            else (
                "最终只返回一个符合 JSON Schema 的对象，格式必须是"
                "{\"payload\":\"...\"}；payload 的值是你本来要返回的 JSON 对象序列化后的单行字符串，"
                "不要使用 Markdown 或代码围栏。\n\n"
            )
        )
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "你现在通过本地 Codex CLI 作为 DemoPilot 的一个 Agent 工作。"
            "只能依据下面给出的客户输入和前序证据作答；不要调用工具、不要读写文件、"
            "不要输出思考过程。"
            + output_instruction
            + build_agent_prompt(agent_id, request, context, iteration=iteration)
        )
        schema_path: Path | None = None
        args = [
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--json",
            "--skip-git-repo-check",
            "-",
        ]
        if not direct_builder:
            schema_path = _schema_file()
            args[7:7] = ["--output-schema", str(schema_path)]
        if self.model:
            args[1:1] = ["--model", self.model]
        if self.reasoning_effort:
            # A bare enum avoids an extra round of escaping when a Windows
            # .cmd shim forwards argv through ``cmd /c``.
            args[1:1] = ["-c", f"model_reasoning_effort={self.reasoning_effort}"]
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
            if on_event is None:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")), timeout=self.timeout_seconds
                )
            else:
                stdout, stderr = await self._communicate_with_events(
                    process, prompt.encode("utf-8"), on_event
                )
        except TimeoutError as exc:
            if process is not None:
                await _terminate_process_tree(process)
            if on_event is not None:
                on_event({"type": "process.timeout"})
            raise RuntimeError(f"Codex CLI agent {agent_id} timed out") from exc
        except asyncio.CancelledError:
            if process is not None:
                await _terminate_process_tree(process)
            if on_event is not None:
                on_event({"type": "process.cancelled"})
            raise
        except OSError as exc:
            raise ProviderUnavailableError("Codex CLI could not be started") from exc
        finally:
            if schema_path is not None:
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

    async def _communicate_with_events(
        self,
        process: asyncio.subprocess.Process,
        prompt: bytes,
        on_event: Callable[[dict[str, Any]], None],
    ) -> tuple[bytes, bytes]:
        """Send one prompt while preserving a safe, metadata-only event trace.

        The normal provider path intentionally uses ``communicate`` for simple
        compatibility with older CLI wrappers. The live DemoPilot path opts in
        here so a run can show whether the authenticated process started,
        emitted JSONL, is still waiting, or exited. Event payloads are reduced
        to types, counters, timings and usage; model text and customer inputs
        never enter the durable trace.
        """

        started = asyncio.get_running_loop().time()
        stdout_bytes = 0
        on_event(
            {
                "type": "process.started",
                "pid": process.pid,
                "model": self.model or "desktop-configured",
                "reasoning_effort": self.reasoning_effort or "desktop-configured",
            }
        )

        async def read_stream(
            stream: asyncio.StreamReader | None,
            *,
            is_stdout: bool,
        ) -> bytes:
            nonlocal stdout_bytes
            if stream is None:
                return b""
            collected = bytearray()
            pending = bytearray()
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                collected.extend(chunk)
                if is_stdout:
                    stdout_bytes += len(chunk)
                    pending.extend(chunk)
                    while b"\n" in pending:
                        raw_line, _, remainder = pending.partition(b"\n")
                        pending = bytearray(remainder)
                        self._emit_jsonl_event(raw_line, on_event, started, stdout_bytes)
            if is_stdout and pending:
                self._emit_jsonl_event(bytes(pending), on_event, started, stdout_bytes)
            return bytes(collected)

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(15)
                on_event(
                    {
                        "type": "process.heartbeat",
                        "elapsed_seconds": round(asyncio.get_running_loop().time() - started, 1),
                        "stdout_bytes": stdout_bytes,
                    }
                )

        if process.stdin is not None:
            process.stdin.write(prompt)
            await process.stdin.drain()
            process.stdin.close()
        stdout_task = asyncio.create_task(read_stream(process.stdout, is_stdout=True))
        stderr_task = asyncio.create_task(read_stream(process.stderr, is_stdout=False))
        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            await asyncio.wait_for(process.wait(), timeout=self.timeout_seconds)
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except BaseException:
            for task in (stdout_task, stderr_task, heartbeat_task):
                task.cancel()
            await asyncio.gather(stdout_task, stderr_task, heartbeat_task, return_exceptions=True)
            raise
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        on_event(
            {
                "type": "process.exited",
                "returncode": process.returncode,
                "elapsed_seconds": round(asyncio.get_running_loop().time() - started, 1),
                "stdout_bytes": stdout_bytes,
            }
        )
        return stdout, stderr

    @staticmethod
    def _emit_jsonl_event(
        raw_line: bytes,
        on_event: Callable[[dict[str, Any]], None],
        started: float,
        stdout_bytes: int,
    ) -> None:
        try:
            event = json.loads(raw_line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        safe: dict[str, Any] = {
            "type": event.get("type", "unknown"),
            "elapsed_seconds": round(asyncio.get_running_loop().time() - started, 1),
            "stdout_bytes": stdout_bytes,
        }
        item = event.get("item")
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            safe["item_type"] = item["type"]
        for key in ("status", "thread_id", "error_code"):
            value = event.get(key)
            if isinstance(value, (str, int, float, bool)):
                safe[key] = value
        usage = event.get("usage")
        if isinstance(usage, dict):
            safe_usage = {
                key: usage[key]
                for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
                if isinstance(usage.get(key), int)
            }
            if safe_usage:
                safe["usage"] = safe_usage
        on_event(safe)
