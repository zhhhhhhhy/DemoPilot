from __future__ import annotations

import asyncio
import json
import sys

import pytest

from demopilot.providers.codex_cli import CodexCliAgentProvider


def test_timeout_retains_partial_output_without_competing_pipe_readers(tmp_path):
    async def scenario():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c",
            "import sys,time; print('{\"type\":\"turn.started\"}',flush=True); "
            "print('partial diagnostic',file=sys.stderr,flush=True); time.sleep(60)",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        provider = CodexCliAgentProvider(timeout_seconds=0.3)
        events = []
        with pytest.raises(TimeoutError):
            await provider._communicate_workspace_process(
                process, b"request", events.append,
                tmp_path / "stdout.jsonl", tmp_path / "stderr.log",
            )
        assert process.returncode is not None
        assert json.loads((tmp_path / "stdout.jsonl").read_text())["type"] == "turn.started"
        assert "partial diagnostic" in (tmp_path / "stderr.log").read_text()
        assert any(event["type"] == "process.timeout" for event in events)

    asyncio.run(asyncio.wait_for(scenario(), 12))


def test_deadline_also_bounds_output_drain_after_wrapper_exits(tmp_path, monkeypatch):
    async def scenario():
        class ExitedWrapper:
            pid = -1
            returncode = 0
            stdin = None
            stdout = asyncio.StreamReader()
            stderr = asyncio.StreamReader()

            async def wait(self):
                return 0

        stopped = []

        async def terminate(_process):
            stopped.append(True)

        monkeypatch.setattr("demopilot.providers.codex_cli._terminate_process_tree", terminate)
        with pytest.raises(TimeoutError):
            await CodexCliAgentProvider(timeout_seconds=0.03)._communicate_workspace_process(
                ExitedWrapper(), b"", lambda _event: None,
                tmp_path / "stdout.jsonl", tmp_path / "stderr.log",
            )
        assert stopped == [True]

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_cancellation_terminates_real_child_and_keeps_streams(tmp_path):
    async def scenario():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c",
            "import time; print('started',flush=True); time.sleep(60)",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        events = []
        task = asyncio.create_task(CodexCliAgentProvider(timeout_seconds=60)._communicate_workspace_process(
            process, b"", events.append, tmp_path / "stdout.jsonl", tmp_path / "stderr.log",
        ))
        for _ in range(100):
            if (tmp_path / "stdout.jsonl").exists() and (tmp_path / "stdout.jsonl").stat().st_size:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.returncode is not None
        assert "started" in (tmp_path / "stdout.jsonl").read_text()
        assert any(event["type"] == "process.cancelled" for event in events)

    asyncio.run(asyncio.wait_for(scenario(), 12))
