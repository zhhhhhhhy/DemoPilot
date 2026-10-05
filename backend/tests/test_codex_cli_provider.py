from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from demopilot.models import DemoRequest
from demopilot.providers.base import ProviderUnavailableError
from demopilot.providers.codex_cli import CodexCliAgentProvider, _final_message


def request() -> DemoRequest:
    return DemoRequest(
        client_name="远山科技",
        project_name="运营指挥台",
        industry="企业服务",
        scenario="运营团队需要识别异常并追踪处理结果。",
        audience="运营负责人",
        must_haves=["异常筛选", "状态追踪"],
        provider="codex_cli",
    )


def test_final_message_extracts_last_agent_message():
    stream = "\n".join(
        [
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"type":"reasoning","text":"hidden"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"status\\":\\"ok\\"}"}}',
        ]
    )
    assert _final_message(stream, "brief") == '{"status":"ok"}'


def test_codex_cli_provider_parses_structured_json(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self, input: bytes | None = None):
            captured["prompt"] = input.decode("utf-8") if input else ""
            message = json.dumps({"payload": json.dumps({"status": "ok"})})
            event = json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": message}}
            )
            return (
                f"{event}\n".encode(),
                b"",
            )

    async def fake_create(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(
        "demopilot.providers.codex_cli.shutil.which",
        lambda _command: r"C:\\Users\\demo\\AppData\\Roaming\\npm\\codex.exe",
    )
    monkeypatch.setattr("demopilot.providers.codex_cli.asyncio.create_subprocess_exec", fake_create)
    provider = CodexCliAgentProvider(cwd=tmp_path)

    result = asyncio.run(provider.run_agent("brief", request(), {"intent_statement": {}}))

    assert result == {"status": "ok"}
    args = list(captured["args"])
    assert "exec" in args
    assert "--json" in args
    assert "--sandbox" in args
    assert "read-only" in args
    assert "--output-schema" in args
    assert args[-1] == "-"
    assert "customer_request" in str(captured["prompt"])
    assert '"payload"' in str(captured["prompt"])
    assert captured["kwargs"]["cwd"] == str(tmp_path)


def test_codex_cli_provider_fails_closed_when_unavailable(monkeypatch):
    monkeypatch.setattr("demopilot.providers.codex_cli.shutil.which", lambda _command: None)
    provider = CodexCliAgentProvider(command="missing-codex")

    with pytest.raises(ProviderUnavailableError, match="not available"):
        asyncio.run(provider.run_agent("brief", request(), {}))


def test_codex_cli_provider_surfaces_nonzero_exit(monkeypatch):
    class FakeProcess:
        returncode = 7

        async def communicate(self, input: bytes | None = None):
            return b"", b"not logged in\n"

    async def fake_create(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "demopilot.providers.codex_cli.shutil.which",
        lambda _command: r"C:\\Users\\demo\\AppData\\Roaming\\npm\\codex.exe",
    )
    monkeypatch.setattr("demopilot.providers.codex_cli.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(RuntimeError, match="not logged in"):
        asyncio.run(CodexCliAgentProvider().run_agent("brief", request(), {}))


def test_codex_cli_provider_timeout_terminates_process_tree(monkeypatch):
    terminated: list[bool] = []

    class FakeProcess:
        returncode = None
        pid = 1234

        async def communicate(self, input: bytes | None = None):
            await asyncio.sleep(1)
            return b"", b""

        async def wait(self):
            return 1

    async def fake_create(*args, **kwargs):
        return FakeProcess()

    async def fake_terminate(_process):
        terminated.append(True)

    monkeypatch.setattr(
        "demopilot.providers.codex_cli.shutil.which",
        lambda _command: r"C:\\Users\\demo\\AppData\\Roaming\\npm\\codex.exe",
    )
    monkeypatch.setattr("demopilot.providers.codex_cli.asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr("demopilot.providers.codex_cli._terminate_process_tree", fake_terminate)

    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(CodexCliAgentProvider(timeout_seconds=0.01).run_agent("brief", request(), {}))
    assert terminated == [True]


def test_codex_cli_provider_serializes_local_cli_calls(monkeypatch):
    active = 0
    max_active = 0

    class FakeProcess:
        returncode = 0

        async def communicate(self, input: bytes | None = None):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            message = json.dumps({"payload": json.dumps({"agent": "ok"})})
            event = json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": message}}
            )
            return f"{event}\n".encode(), b""

    async def fake_create(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "demopilot.providers.codex_cli.shutil.which",
        lambda _command: r"C:\\Users\\demo\\AppData\\Roaming\\npm\\codex.exe",
    )
    monkeypatch.setattr("demopilot.providers.codex_cli.asyncio.create_subprocess_exec", fake_create)

    async def run_both():
        provider = CodexCliAgentProvider()
        return await asyncio.gather(
            provider.run_agent("brief", request(), {}),
            provider.run_agent("manager", request(), {}),
        )

    assert asyncio.run(run_both()) == [{"agent": "ok"}, {"agent": "ok"}]
    assert max_active == 1
