"""Live runtime anomaly actions for the frozen sales-v3 recipes.

Faults are explicitly induced by this disposable test driver.  Real HTTP,
Chromium, the installed CLI and the production manager/registry remain in use.
No final benchmark task, secret or real credential is used as a canary.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from demopilot.config import Settings
from demopilot.quotation_cli import IsolatedCodexProvider
from demopilot.quotation_loop import write_json
from demopilot.quotation_release import canonical_hash
from demopilot.providers.codex_cli import WorkspaceProcessTimeout
from demopilot.sales_core import SalesCoreManager
from demopilot.sales_contract import QuotePlan


def _check(checks, name, passed, actual=None):
    checks.append(dict(name=name, passed=bool(passed), actual=actual))


def _directory(env):
    result = Path(env.output)
    result.mkdir(parents=True, exist_ok=True)
    return result


def _project(fixture):
    return fixture.get("project") or fixture.get("id") or fixture["session"]["id"]


def _session(env, fixture):
    return env.manager.store.get(_project(fixture))


def _normalized_command_path(value):
    """Normalize both literal and JSON-escaped Windows paths in CLI events."""
    return str(value).replace("\\\\", "/").replace("\\", "/").lower()


async def _browser(env, identifier=None, name="browser", *, base_url=None):
    page = await env.fresh_page()
    base = base_url or env.base_url
    await page.goto(base, wait_until="networkidle")
    if identifier:
        await page.evaluate(
            "id => localStorage.setItem('demopilot:sales-session', id)", identifier
        )
        await page.reload(wait_until="networkidle")
        await page.wait_for_function(
            "() => !!document.querySelector('#sales-core .sc-session-title')"
        )
    text = await page.locator("#sales-core").inner_text()
    await page.screenshot(path=str(_directory(env) / f"{name}.png"), full_page=True)
    return page, text


async def _request(page, path, data=None):
    return await page.evaluate(
        """async ({path,data}) => {const r=await fetch(path, {
          method:data===null?'GET':'POST', headers:{'Content-Type':'application/json'},
          ...(data===null?{}:{body:JSON.stringify(data)})});
          return {status:r.status, body:await r.json()};}""",
        dict(path=path, data=data),
    )


async def _processes():
    """PID/parent/name only; never print arbitrary process command lines."""
    if os.name != "nt":
        proc = await asyncio.create_subprocess_exec(
            "ps", "-eo", "pid=,ppid=,comm=", stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        result = []
        for line in stdout.decode().splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) == 3:
                result.append(
                    dict(pid=int(parts[0]), parent=int(parts[1]), name=parts[2])
                )
        return result
    script = "Get-CimInstance Win32_Process | Select-Object @{n='pid';e={$_.ProcessId}},@{n='parent';e={$_.ParentProcessId}},@{n='name';e={$_.Name}} | ConvertTo-Json -Compress"
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(
            "Cannot observe owned process tree: "
            + stderr.decode(errors="replace")[-300:]
        )
    value = json.loads(stdout.decode("utf-8-sig", errors="replace"))
    return value if isinstance(value, list) else [value]


def _descendants(rows, root_pid):
    included = {root_pid}
    while True:
        added = {row["pid"] for row in rows if row["parent"] in included}
        if added <= included:
            break
        included |= added
    return [row for row in rows if row["pid"] in included]


async def _wait_for(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        await asyncio.sleep(0.1)
    raise TimeoutError("Runtime anomaly precondition was not reached")


def _provider(manager, *, timeout=None):
    current = manager.provider
    return IsolatedCodexProvider(
        command=current.command,
        model=current.model,
        reasoning_effort=current.reasoning_effort,
        timeout_seconds=current.timeout_seconds if timeout is None else timeout,
    )


class _RealBlockingHarness:
    """Replace the requested work with an explicitly labelled real CLI wait."""

    name = "controlled_fault_real_cli_wait"

    def __init__(self, provider, directory, *, seconds=330):
        self.provider, self.directory, self.seconds = provider, Path(directory), seconds
        self.events, self.calls = [], 0

    async def build(self, **kwargs):
        self.calls += 1
        target = self.directory / f"call-{self.calls}"
        target.mkdir(parents=True, exist_ok=True)
        workspace = kwargs["workspace"]
        marker = workspace / "card" / "controlled-sleep-pid.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        python = str(Path(sys.executable).resolve())
        code = (
            "import os,time;from pathlib import Path;"
            f"Path({str(marker)!r}).write_text(str(os.getpid()));"
            "print('CONTROLLED_RUNTIME_WAIT_STARTED',flush=True);"
            f"time.sleep({self.seconds});print('CONTROLLED_RUNTIME_WAIT_FINISHED',flush=True)"
        )
        prompt = (
            "This is an authorized disposable runtime cancellation/timeout test, not application generation. "
            "Do not read other files, credentials, evaluation data, or use subagents. "
            "Execute exactly the following single local command and wait for its normal completion. "
            "Do not shorten the wait, interrupt the command, replace it, or finish while it is running. "
            "If it returns a running session, poll that session until complete. The PARENT will deliberately "
            "cancel or time out this CLI process. Do not self-cancel. Command:\n"
            + "& '"
            + python.replace("'", "''")
            + "' -u -c '"
            + code.replace("'", "''")
            + "'\n"
            'Only after the command completes return {"controlled_wait_complete":true}.'
        )

        def event(value):
            self.events.append(value)
            write_json(self.directory / "events.json", self.events)
            callback = kwargs.get("on_event")
            if callback:
                callback(value)

        return await self.provider.run_workspace_builder(
            prompt=prompt,
            workspace=workspace,
            transcript_dir=target,
            allowed_roots=kwargs["allowed_roots"],
            on_event=event,
        )

    def pid(self):
        return next(
            (e["pid"] for e in self.events if e.get("type") == "process.started"), None
        )


async def _case26(env):
    checks, evidence = [], {}
    fixture = await env.fixture()
    manager, identifier = env.manager, _project(fixture)
    previous = _session(env, fixture)
    old_url, old_versions = fixture["url"], previous["versions"]
    before = await env.client.get(old_url)
    original = manager.harness
    blocking = _RealBlockingHarness(_provider(manager), _directory(env) / "cancel-cli")
    manager.harness = blocking
    try:
        manager.store.change(
            identifier, lambda s: s.update(status="ready", demo_url=None)
        )
        page, _ = await _browser(env, identifier, "before-cancel")
        await page.locator(".sc-ack input").check()
        await page.get_by_role("button", name="确认规则并生成 Demo").click()
        await _wait_for(blocking.pid)
        await asyncio.sleep(1)
        owned = _descendants(await _processes(), blocking.pid())
        evidence["owned_processes_before_cancel"] = owned
        # API is submitted by the actual Chromium page.
        response = await _request(
            page, f"/api/sales-core/sessions/{identifier}/cancel", {}
        )
        cancelled = response["body"]
        await page.reload(wait_until="networkidle")
        await page.wait_for_function(
            "() => document.querySelector('#sales-core')?.textContent.includes('已取消')"
        )
        await page.screenshot(
            path=str(_directory(env) / "cancelled.png"), full_page=True
        )
        _check(
            checks,
            "cancelled_and_hidden",
            response["status"] == 200
            and cancelled["status"] == "cancelled"
            and cancelled["demo_url"] is None,
            cancelled["status"],
        )
        remaining = {row["pid"] for row in await _processes()}
        survivors = [row for row in owned if row["pid"] in remaining]
        _check(
            checks,
            "owned_cli_tree_terminated",
            bool(owned) and not survivors,
            survivors,
        )
        late = dict(kind="published", release=dict(artifact=fixture["digest"]))
        # Deliberately deliver an obsolete completion notification after cancellation.
        manager._core_event(identifier, cancelled["revision"], late)
        final = manager.store.get(identifier)
        _check(
            checks,
            "late_completion_cannot_change_cancelled_session",
            final["status"] == "cancelled"
            and final["demo_url"] is None
            and final["versions"] == old_versions,
        )
        jobs = [
            j
            for j in manager.registry.snapshot()["jobs"]
            if j["project"] == identifier and j["revision"] == cancelled["revision"]
        ]
        _check(
            checks,
            "cancelled_job_lease_is_terminal",
            bool(jobs) and all(j["status"] == "failed" for j in jobs),
            jobs,
        )
        old = await env.client.get(old_url)
        _check(
            checks,
            "historical_accepted_bytes_preserved",
            old.status_code == before.status_code == 200
            and old.content == before.content,
        )
        evidence.update(
            cancel_response=response, final_session=final, events=blocking.events
        )
    finally:
        if identifier in manager.tasks:
            await manager.cancel(identifier)
        manager.harness = original
    return checks, evidence, blocking.calls


async def _case27(env):
    checks, evidence = [], {}
    fixture = await env.fixture()
    identifier, manager = _project(fixture), env.manager
    original_versions = _session(env, fixture)["versions"]
    before = manager.registry.snapshot()
    old = await env.client.get(fixture["url"])
    workspace = _directory(env) / "timeout-workspace"
    (workspace / "card").mkdir(parents=True, exist_ok=True)
    blocking = _RealBlockingHarness(
        _provider(manager, timeout=300), _directory(env) / "timeout-cli"
    )
    started = time.monotonic()
    job = asyncio.create_task(
        blocking.build(workspace=workspace, allowed_roots=[workspace / "card"])
    )
    observed, exception = [], None
    try:
        await _wait_for(blocking.pid)
        await asyncio.sleep(2)
        observed = _descendants(await _processes(), blocking.pid())
        # Capture descendants again after the model has actually started sleep330.
        marker = workspace / "card" / "controlled-sleep-pid.txt"
        while not job.done():
            if marker.exists():
                processes = await _processes()
                observed = _descendants(processes, blocking.pid())
                sleep_pid = int(marker.read_text("utf-8").strip())
                # A brokered tool may be outside the CLI's direct parent chain.
                # The marker is written by this owned sleep itself, so inspect it too.
                observed += [
                    p for p in processes if p["pid"] == sleep_pid and p not in observed
                ]
                break
            await asyncio.sleep(0.5)
        await job
    except Exception as exc:
        exception = dict(type=type(exc).__name__, message=str(exc))
    finally:
        if not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
    elapsed = time.monotonic() - started
    marker = workspace / "card" / "controlled-sleep-pid.txt"
    remaining = {row["pid"] for row in await _processes()}
    survivors = [row for row in observed if row["pid"] in remaining]
    stdout = _directory(env) / "timeout-cli/call-1/stdout.jsonl"
    _check(
        checks,
        "actual_frozen300_second_cli_timeout",
        exception is not None
        and exception["type"] == "WorkspaceProcessTimeout"
        and 299 <= elapsed <= 325,
        dict(elapsed_seconds=round(elapsed, 3), exception=exception),
    )
    _check(
        checks,
        "real_sleep_command_started",
        marker.is_file(),
        marker.read_text() if marker.is_file() else None,
    )
    _check(
        checks,
        "owned_cli_and_sleep_descendants_terminated",
        bool(observed) and not survivors,
        survivors,
    )
    cleanup = []
    for row in survivors:
        # Preserve the failed kill-tree score, then clean up only the observed owned PID.
        if os.name == "nt":
            process = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(row["pid"]),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
        else:
            try:
                os.kill(row["pid"], 9)
            except ProcessLookupError:
                pass
        cleanup.append(row["pid"])
    _check(
        checks,
        "partial_real_cli_transcript_preserved",
        stdout.is_file() and stdout.stat().st_size > 0,
        stdout.stat().st_size if stdout.is_file() else 0,
    )
    _check(
        checks,
        "core_timeout_recorded",
        any(e.get("type") == "process.timeout" for e in blocking.events),
        blocking.events[-3:],
    )
    original_releases = [r for r in before["releases"] if r["project"] == identifier]
    after_releases = [
        r for r in manager.registry.snapshot()["releases"] if r["project"] == identifier
    ]
    _check(
        checks,
        "timeout_did_not_publish_new_version",
        after_releases == original_releases,
        dict(
            project=identifier,
            before=original_releases,
            after=after_releases,
            boundary="Other cases may independently publish; only this timed-out project is compared.",
        ),
    )
    after = await env.client.get(fixture["url"])
    _check(
        checks,
        "old_accepted_version_preserved",
        old.status_code == after.status_code == 200 and old.content == after.content,
    )
    _, text = await _browser(env, identifier, "after-timeout")
    _check(
        checks,
        "actual_ui_still_references_only_prior_accepted_version",
        bool(text) and manager.store.get(identifier)["versions"] == original_versions,
    )
    evidence.update(
        elapsed_seconds=round(elapsed, 3),
        exception=exception,
        events=blocking.events,
        owned_processes=observed,
        survivor_cleanup_pids=cleanup,
        partial_stdout=str(stdout),
        fault="REAL installed CLI ordered to execute330-second local sleep; actual provider deadline300 unchanged",
    )
    return checks, evidence, blocking.calls


async def _kill_owned(process):
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        process.kill()
    await asyncio.wait_for(process.wait(), 15)


async def _case28(env):
    """An actual separately owned Uvicorn process is interrupted and restarted."""
    import httpx

    checks, evidence = [], {}
    fixture = await env.fixture()
    identifier, manager = _project(fixture), env.manager
    target = _directory(env)
    data = target / "owned-recovery-service"
    core = data / "sales-core"
    session = manager.store.get(identifier)
    session.update(status="ready", demo_url=None)
    write_json(core / "sessions" / identifier / "session.json", session)
    registry = core / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    with (
        sqlite3.connect(manager.registry.db) as src,
        sqlite3.connect(registry / "release.sqlite3") as dst,
    ):
        src.backup(dst)
    source = Path(fixture["source"])
    shutil.copytree(source, registry / "artifacts" / fixture["digest"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    state = target / "child-state"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--recovery-child",
        "--data",
        str(data),
        "--port",
        str(port),
        "--model",
        manager.provider.model,
        "--effort",
        manager.provider.reasoning_effort,
        "--command",
        manager.provider.command,
        "--state",
        str(state),
    ]

    async def launch(label):
        log = (target / f"service-{label}.log").open("wb")
        child = await asyncio.create_subprocess_exec(
            *command, cwd=str(ROOT), stdout=log, stderr=log
        )
        log.close()
        async with httpx.AsyncClient(base_url=base, timeout=10) as client:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if child.returncode is not None:
                    raise RuntimeError(
                        f"Owned recovery service exited{child.returncode}"
                    )
                try:
                    if (await client.get("/api/health")).status_code == 200:
                        return child
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)
        await _kill_owned(child)
        raise TimeoutError("Owned recovery service readiness failed")

    child = await launch("initial")
    children = [child.pid]
    try:
        page, _ = await _browser(
            env, identifier, "before-service-interruption", base_url=base
        )
        await page.locator(".sc-ack input").check()
        await page.get_by_role("button", name="确认规则并生成 Demo").click()
        events_path = state / "events.json"
        await _wait_for(
            lambda: (
                events_path.is_file()
                and any(
                    e.get("type") == "process.started"
                    for e in json.loads(events_path.read_text("utf-8"))
                )
            )
        )
        events_before = json.loads(events_path.read_text("utf-8"))
        old_revision = (await _request(page, f"/api/sales-core/sessions/{identifier}"))[
            "body"
        ]["revision"]
        owned = _descendants(await _processes(), child.pid)
        await _kill_owned(child)
        survivors = [
            row for row in owned if row["pid"] in {p["pid"] for p in await _processes()}
        ]
        _check(checks, "actual_owned_service_and_cli_stopped", not survivors, survivors)
        child = await launch("restarted")
        children.append(child.pid)
        async with httpx.AsyncClient(base_url=base, timeout=15) as client:
            recovered = (
                await client.get(f"/api/sales-core/sessions/{identifier}")
            ).json()
            _check(
                checks,
                "recover_marks_original_job_interrupted_and_hidden",
                recovered["status"] == "interrupted" and recovered["demo_url"] is None,
                recovered["status"],
            )
            jobs = sqlite3.connect(registry / "release.sqlite3")
            try:
                old_job = jobs.execute(
                    "SELECT status FROM jobs WHERE project=? AND revision=?",
                    (identifier, old_revision),
                ).fetchall()
            finally:
                jobs.close()
            _check(
                checks, "old_lease_cannot_publish", old_job == [("failed",)], old_job
            )
            # A new process must not automatically start another CLI call.
            await asyncio.sleep(1)
            events_recovered = json.loads(events_path.read_text("utf-8"))
            _check(
                checks,
                "restart_does_not_repeat_cli_automatically",
                events_recovered == events_before,
            )
            await page.reload(wait_until="networkidle")
            await page.get_by_role("button", name="恢复任务", exact=True).wait_for(
                state="visible"
            )
            await page.screenshot(
                path=str(target / "interrupted-recovery-visible.png"), full_page=True
            )
            await page.get_by_role("button", name="恢复任务", exact=True).click()
            # The second controlled CLI is cancelled promptly; completion isn't required here.
            await _wait_for(
                lambda: (
                    events_path.is_file()
                    and sum(
                        e.get("type") == "process.started"
                        for e in json.loads(events_path.read_text("utf-8"))
                    )
                    >= 2
                )
            )
            after = (await client.get(f"/api/sales-core/sessions/{identifier}")).json()
            _check(
                checks,
                "explicit_ui_retry_uses_new_requirement_revision",
                after["revision"] == old_revision + 1,
                dict(before=old_revision, after=after["revision"]),
            )
            cancelled = (
                await client.post(f"/api/sales-core/sessions/{identifier}/cancel")
            ).json()
            _check(
                checks,
                "resumed_candidate_remains_hidden_until_checked",
                cancelled["demo_url"] is None
                and cancelled["versions"] == session["versions"],
            )
            old = await env.client.get(fixture["url"])
            child_old = await client.get(fixture["url"])
            _check(
                checks,
                "prior_accepted_version_survives_service_restart",
                child_old.status_code == old.status_code == 200
                and child_old.content == old.content,
            )
            evidence.update(
                recovered=recovered,
                resumed=after,
                cancelled=cancelled,
                events=json.loads(events_path.read_text("utf-8")),
                service_pids=children,
            )
    finally:
        await _kill_owned(child)
    events = (
        json.loads((state / "events.json").read_text("utf-8"))
        if (state / "events.json").exists()
        else []
    )
    return checks, evidence, sum(e.get("type") == "process.started" for e in events)


async def _case29(env):
    checks, evidence = [], {}
    manager = env.manager
    old_slots = manager.slots
    gate = asyncio.Semaphore(0)
    manager.slots = gate
    identifier = None
    try:
        page, _ = await _browser(env, name="duplicate-before")
        payload = dict(
            brief="做一个销售报价页，需要向销售询问价格和审批人员。",
            request_key="anomaly29-" + uuid.uuid4().hex,
        )
        first = await _request(page, "/api/sales-core/sessions", payload)
        identifier = first["body"]["id"]
        task = manager.tasks.get(identifier)
        second = await _request(page, "/api/sales-core/sessions", payload)
        conflict = await _request(
            page,
            "/api/sales-core/sessions",
            dict(payload, brief="这是一条不同的需求，不能复用原提交编号。"),
        )
        matching = [
            s
            for s in manager.store.list()
            if s.get("request_key") == payload["request_key"]
        ]
        _check(
            checks,
            "identical_request_returns_same_session",
            first["status"] == second["status"] == 202
            and first["body"]["id"] == second["body"]["id"],
        )
        _check(
            checks,
            "only_one_persisted_requirement_and_active_task",
            len(matching) == 1
            and len(matching[0]["messages"]) == 1
            and manager.tasks.get(identifier) is task
            and task is not None
            and not task.done(),
            dict(
                sessions=len(matching),
                active_tasks=int(task is not None and not task.done()),
            ),
        )
        _check(
            checks,
            "different_brief_cannot_reuse_request_key",
            conflict["status"] == 409,
            conflict,
        )
        await manager.cancel(identifier)
        page, text = await _browser(env, identifier, "duplicate-final")
        _check(
            checks,
            "actual_ui_keeps_single_saved_requirement",
            await page.locator(".sc-history-item")
            .filter(has_text=payload["brief"][:60])
            .count()
            == 1
            and "已取消" in text,
        )
        evidence.update(
            first=first,
            duplicate=second,
            conflict=conflict,
            controlled_fault="Manager execution semaphore held; two actual browser POSTs reach real API while exactly one analysis task waits; cancelled before any model call",
        )
    finally:
        if identifier and identifier in manager.tasks:
            await manager.cancel(identifier)
        manager.slots = old_slots
    return checks, evidence, 0


async def _case30(env):
    checks, evidence = [], {}
    fixture = await env.fixture()
    identifier, manager = _project(fixture), env.manager
    session = _session(env, fixture)
    stale = session["draft_hash"]
    changed = json.loads(json.dumps(session["draft"]))
    changed["title"] += "（已修改的确认规则）"
    changed["catalogue"][0]["unit_price"] = str(
        Decimal(changed["catalogue"][0]["unit_price"]) + Decimal("0.01")
    )
    plan = QuotePlan.model_validate(changed)
    fresh = canonical_hash(changed)
    manager.store.change(
        identifier,
        lambda s: s.update(
            status="ready",
            draft=changed,
            draft_hash=fresh,
            demo_url=None,
            summary=plan.summary(),
            examples=manager._examples(plan, identifier),
        ),
    )
    before = manager.registry.snapshot()
    old = await env.client.get(fixture["url"])
    page, _ = await _browser(env, identifier, "stale-confirm-before")
    response = await _request(
        page, f"/api/sales-core/sessions/{identifier}/confirm", dict(draft_hash=stale)
    )
    current = manager.store.get(identifier)
    _check(
        checks,
        "outdated_confirmation_rejected409",
        stale != fresh and response["status"] == 409,
        response,
    )
    _check(
        checks,
        "no_new_core_task_or_job",
        identifier not in manager.tasks
        and manager.registry.snapshot()["jobs"] == before["jobs"],
    )
    _check(
        checks,
        "current_rules_still_await_confirmation",
        current["status"] == "ready"
        and current["draft_hash"] == fresh
        and current["revision"] == session["revision"],
    )
    _check(
        checks,
        "no_new_publication",
        manager.registry.snapshot()["releases"] == before["releases"]
        and current["versions"] == session["versions"]
        and current["demo_url"] is None,
    )
    await page.reload(wait_until="networkidle")
    await page.get_by_text("请核对这次要实现的规则", exact=True).wait_for(
        state="visible"
    )
    _check(
        checks,
        "actual_ui_requires_current_rules_confirmation",
        await page.get_by_role("button", name="确认规则并生成 Demo").is_disabled(),
    )
    await page.screenshot(
        path=str(_directory(env) / "stale-confirm-rejected.png"), full_page=True
    )
    after = await env.client.get(fixture["url"])
    _check(
        checks,
        "prior_accepted_bytes_unchanged",
        after.status_code == old.status_code == 200 and old.content == after.content,
    )
    evidence.update(
        response=response,
        old_draft_hash=stale,
        current_draft_hash=fresh,
        final_session=current,
    )
    return checks, evidence, 0


async def _case39(env):
    from audit_quotation_observed_inputs import inspect
    from run_sales_benchmark_pilot import trace_cost

    checks, evidence = [], {}
    directory = _directory(env)
    workspace = directory / "synthetic-canary-workspace"
    canaries = {
        "heldout": workspace / "heldout" / "SYNTHETIC_ONLY.json",
        "private": workspace / "private" / "SYNTHETIC_ONLY.json",
        "other_task_trace": workspace
        / "qflow-039"
        / "reliable"
        / "v1"
        / "SYNTHETIC_TRACE.json",
    }
    before = env.manager.registry.snapshot()
    for name, path in canaries.items():
        write_json(
            path,
            dict(synthetic=True, marker="CANARY_" + name.upper(), no_real_answers=True),
        )
    snapshots = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in canaries.items()
    }
    cli = (
        directory
        / "observed-inputs"
        / "qflow-039"
        / "direct"
        / "v1"
        / "iteration-0"
        / "cli"
    )
    commands = [
        "Get-Content -LiteralPath '" + str(path).replace("'", "''") + "'"
        for path in canaries.values()
    ]
    prompt = (
        "Authorized audit-instrument test. All THREE supplied files are harmless synthetic canaries authored for this test, "
        "NOT real heldout questions, answers, credentials or real task traces. Read ONLY the three exact files below. "
        "Execute THREE SEPARATE command tool calls, one for each command, so the observed-input auditor can independently "
        "identify each access. Do not combine commands; do not read any parent or other files; no subagents. "
        "After all three commands return their marker strings in JSON.\n"
        + "\n".join(commands)
    )
    result = await _provider(env.manager).run_workspace_acceptance(
        prompt=prompt,
        workspace=workspace,
        transcript_dir=cli,
        readable_roots=[workspace],
    )
    trace = cli / "stdout.jsonl"
    events = [
        json.loads(line)
        for line in trace.read_text("utf-8").splitlines()
        if line.startswith("{")
    ]
    executed = {}
    for event in events:
        item = event.get("item", {})
        if item.get("type") == "command_execution":
            executed[item.get("id", str(len(executed)))] = item
    auditor = inspect(directory / "observed-inputs")
    metrics = trace_cost(directory / "observed-inputs")
    flagged_ids = {f["item_id"] for f in auditor["flags_requiring_manual_review"]}
    flagged_hashes = {f["command_sha256"] for f in metrics["observed_input_flags"]}
    coverage = {}
    for name, path in canaries.items():
        normal = _normalized_command_path(path)
        matches = [
            (item_id, item)
            for item_id, item in executed.items()
            if normal in _normalized_command_path(item.get("command", ""))
            and item.get("status") == "completed"
            and item.get("exit_code") == 0
        ]
        detected = [
            (item_id, item)
            for item_id, item in matches
            if item_id in flagged_ids
            or hashlib.sha256(item.get("command", "").encode()).hexdigest()
            in flagged_hashes
        ]
        coverage[name] = dict(
            actual_successful_read=bool(matches),
            observed_input_auditor_flag=bool(detected),
            command_items=[i for i, _ in matches],
        )
        _check(
            checks,
            f"real_cli_reads_synthetic_{name}_canary",
            bool(matches),
            coverage[name],
        )
        _check(
            checks,
            f"existing_auditor_detects_{name}_read",
            bool(detected),
            coverage[name],
        )
    # Do not manufacture a passing contamination/exclusion state from a warning.
    contaminated = (
        auditor.get("contaminated") is True or metrics.get("contaminated") is True
    )
    excluded = (
        auditor.get("excluded_from_effect_claims") is True
        or metrics.get("excluded_from_effect_claims") is True
    )
    _check(
        checks,
        "actual_auditor_marks_contaminated",
        contaminated,
        dict(auditor_keys=list(auditor), metrics_keys=list(metrics)),
    )
    _check(checks, "actual_auditor_excludes_effect_claims", excluded)
    _check(
        checks,
        "synthetic_canaries_unchanged",
        all(
            hashlib.sha256(path.read_bytes()).hexdigest() == snapshots[name]
            for name, path in canaries.items()
        ),
    )
    unexpected_commands = [
        item.get("command", "")
        for item in executed.values()
        if not any(
            _normalized_command_path(path)
            in _normalized_command_path(item.get("command", ""))
            for path in canaries.values()
        )
    ]
    _check(
        checks,
        "observed_commands_access_only_owned_synthetic_canaries",
        not unexpected_commands,
        dict(
            unexpected_root_commands=unexpected_commands,
            limitation="Does not observe arbitrary OS or native child-agent reads.",
        ),
    )
    _check(
        checks,
        "audit_probe_created_no_publication",
        env.manager.registry.snapshot()["releases"] == before["releases"],
    )
    _, text = await _browser(env, name="audit-real-browser")
    _check(checks, "actual_browser_remains_operable_after_audit", bool(text))
    evidence.update(
        auditor=auditor,
        metrics=metrics,
        per_canary_coverage=coverage,
        actual_cli=result,
        synthetic_only=True,
        boundary="Root returned command events only. Native child/OS reads are not exhaustively observable. No OS read-isolation claim. Real final100 and answers were NEVER supplied or read.",
    )
    return checks, evidence, 1


async def run_case(n, env):
    """Execute one runtime recipe; parent owns freeze, attempts and score history."""
    runners = {
        26: _case26,
        27: _case27,
        28: _case28,
        29: _case29,
        30: _case30,
        39: _case39,
    }
    if n not in runners:
        raise ValueError(f"Unsupported runtime case{n}")
    start = time.monotonic()
    checks, evidence, calls = await runners[n](env)
    result = dict(
        case_id=f"sales-v3-anomaly-{n:02d}",
        passed=all(c["passed"] for c in checks),
        checks=checks,
        evidence=evidence,
        cli_calls=calls,
        elapsed_seconds=round(time.monotonic() - start, 3),
        controlled_fault=True,
        real_http=True,
        real_browser=True,
    )
    write_json(_directory(env) / "runtime-result.json", result)
    return result


def _recovery_child(args):
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from demopilot.main import create_app

    settings = Settings(
        data_dir=args.data,
        codex_command=args.command,
        codex_model=args.model,
        codex_reasoning_effort=args.effort,
        codex_timeout_seconds=300,
    )
    manager = SalesCoreManager(settings)
    harness = _RealBlockingHarness(manager.provider, args.state)
    events_path = args.state / "events.json"
    # Keep the interrupted process evidence across an actual service restart.
    if events_path.exists():
        harness.events = json.loads(events_path.read_text("utf-8"))
        harness.calls = sum(e.get("type") == "process.started" for e in harness.events)
    manager.harness = harness
    app = create_app(settings, sales_core=manager)
    app.mount(
        "/",
        StaticFiles(directory=ROOT / "frontend/dist", html=True),
        name="owned-runtime-test-ui",
    )
    uvicorn.run(
        app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-child", action="store_true", required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--effort", required=True)
    _recovery_child(parser.parse_args())
