"""Two real CLI probes, no business/private inputs, no automatic retry budget."""
# ruff: noqa: E402 -- load the repository-local backend, same as pilot runner.
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "scripts")]
from demopilot.quotation_cli import IsolatedCodexProvider
from demopilot.quotation_loop import write_json
from run_sales_benchmark_pilot import code_manifest, sha, trace_cost


async def run(output: Path, model: str):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / "workspace"
    workspace.mkdir()
    if Path(sys.executable).resolve() != (ROOT / "backend/.venv/Scripts/python.exe").resolve():
        raise RuntimeError("Use backend/.venv/Scripts/python.exe, same as original40")
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content('<button onclick="this.textContent=\'clicked\'">ready</button>')
        await page.get_by_role("button", name="ready").click()
        browser_preflight = dict(passed=await page.get_by_role("button", name="clicked").count() == 1, version=browser.version)
        await browser.close()
    if not browser_preflight["passed"]:
        raise RuntimeError("Actual Chromium click failed")
    provider = IsolatedCodexProvider(command="codex.cmd", model=model, reasoning_effort="medium", timeout_seconds=300)
    rows = []
    started = time.monotonic()
    for mode in ("read", "write"):
        call_started = time.monotonic()
        transcript = output / mode
        try:
            if mode == "read":
                result = await provider.run_workspace_acceptance(
                    prompt='Transport diagnostic only. Do not call tools or subagents. Return exactly {"transport_probe":"ready"}.',
                    workspace=workspace, transcript_dir=transcript, readable_roots=[])
            else:
                result = await provider.run_workspace_builder(
                    prompt="Transport and local workspace diagnostic only. Use a shell tool to write the literal ASCII text READY (no newline) into probe-marker.txt in the current working directory. Do not change anything else. Do not spawn subagents. Then reply READY.",
                    workspace=workspace, transcript_dir=transcript, allowed_roots=[])
            events = [json.loads(s) for s in (transcript / "stdout.jsonl").read_text("utf-8").splitlines() if s.startswith("{")]
            passed = any(e.get("type") == "turn.completed" for e in events)
            if mode == "write":
                passed = passed and (workspace / "probe-marker.txt").read_bytes() == b"READY"
            else:
                passed = passed and any(e.get("item", {}).get("text") == '{"transport_probe":"ready"}' for e in events)
            rows.append(dict(mode=mode, passed=passed, returncode=result["returncode"], elapsed_seconds=round(time.monotonic() - call_started, 2)))
        except Exception as exc:
            rows.append(dict(mode=mode, passed=False, error=str(exc), elapsed_seconds=round(time.monotonic() - call_started, 2)))
        print(json.dumps(rows[-1]), flush=True)
        if not rows[-1]["passed"]:
            break
    record = dict(created_at=datetime.now(UTC).isoformat(), status="passed" if len(rows) == 2 and all(r["passed"] for r in rows) else "failed", rows=rows,
        model=model, reasoning_effort="medium", cli_timeout_seconds=300, code_sha256=code_manifest(),
        elapsed_seconds=round(time.monotonic() - started, 2), cost=trace_cost(output),
        trace_sha256={p.relative_to(output).as_posix(): sha(p) for p in output.rglob("*") if p.name in {"stdout.jsonl", "stderr.log"}},
        data_access="No benchmark business inputs or hidden answers supplied.",
        diagnostic_source_sha256=sha(Path(__file__)))
    record.update(browser_preflight=browser_preflight, python_executable=str(Path(sys.executable).resolve()),
                  transport="official ChatGPT HTTPS/SSE, same local ChatGPT auth; WebSocket disabled")
    write_json(output / "results.json", record)
    print(json.dumps(dict(status=record["status"], output=str(output))), flush=True)
    return record["status"] == "passed"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6.1-sol")
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(run(args.output, args.model)) else 1)
