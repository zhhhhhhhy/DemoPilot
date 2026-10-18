"""Read-only metrics derived from persisted run state and canonical CLI logs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DemoRun, RunStatus

TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def cli_session_metrics(stdout_path: Path, root: Path) -> dict[str, Any]:
    usage: dict[str, int] = {}
    usage_events = 0
    completed_turns = 0
    failure_signals: set[str] = set()
    if stdout_path.is_file():
        for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "turn.completed":
                completed_turns += 1
                values = event.get("usage")
                if isinstance(values, dict):
                    valid = {key: values[key] for key in TOKEN_KEYS if type(values.get(key)) is int and values[key] >= 0}
                    if valid:
                        usage_events += 1
                        for key, value in valid.items():
                            usage[key] = usage.get(key, 0) + value
            if event.get("type") in {"error", "turn.failed"}:
                failure_signals.add("cli_error")
    stderr_path = stdout_path.with_name("stderr.log")
    if not stderr_path.exists() and stdout_path.name.endswith("-stdout.jsonl"):
        stderr_path = stdout_path.with_name(stdout_path.name.replace("-stdout.jsonl", "-stderr.log"))
    diagnostic = stderr_path.read_text(encoding="utf-8", errors="replace").lower() if stderr_path.is_file() else ""
    for key, markers in {
        "transport": ("tls handshake", "workspace routing discovery failed", "stream disconnected"),
        "stream_reader_conflict": ("another coroutine is already waiting",),
    }.items():
        if any(marker in diagnostic for marker in markers):
            failure_signals.add(key)
    return {
        "stdout": str(stdout_path.relative_to(root)).replace("\\", "/"),
        "role": "acceptance_child" if "acceptance-child" in stdout_path.parts else "intent" if "intent" in stdout_path.parts else "builder",
        "completed_turns": completed_turns,
        "usage_events": usage_events,
        "usage": usage or None,
        "observed_failure_signals": sorted(failure_signals),
    }


def run_metrics(run: DemoRun, run_dir: Path) -> dict[str, Any]:
    core = run.outputs.get("core_builder", {})
    iterations = core.get("iterations", []) if isinstance(core, dict) else []
    sessions = []
    seen: set[Path] = set()
    for path in sorted((run_dir / "artifacts" / "evidence" / "core").glob("**/stdout.jsonl")):
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        sessions.append(cli_session_metrics(path, run_dir))
    totals: dict[str, int] = {}
    for session in sessions:
        for key, value in (session["usage"] or {}).items():
            totals[key] = totals.get(key, 0) + value
    signals = sorted({value for session in sessions for value in session["observed_failure_signals"]})
    errors = [str(item.get("error", "")) for item in iterations if isinstance(item, dict)]
    for item in iterations:
        child = item.get("acceptance_child", {}) if isinstance(item, dict) else {}
        if isinstance(child, dict):
            errors.append(str(child.get("error", "")))
    if any("timed out" in value.lower() for value in errors):
        signals = sorted(set(signals) | {"timeout"})
    terminal = run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    failures = [item for item in iterations if isinstance(item, dict) and item.get("acceptance", {}).get("status") == "failed"]
    published = run.publication_status == "published"
    return {
        "schema_version": "demopilot-run-metrics-v1",
        "run_id": run.id,
        "case_id": run.request.evaluation_case_id,
        "status": run.status.value,
        "publication_status": run.publication_status,
        "terminal": terminal,
        "persisted_elapsed_seconds": round(max(0.0, (run.updated_at - run.created_at).total_seconds()), 3) if terminal else None,
        "recorded_agent_calls": run.agent_calls,
        "core_iteration_count": len(iterations),
        "core_revision_count": run.revision_count,
        "failed_core_acceptance_attempts": len(failures),
        "observed_cli_session_count": len(sessions),
        "sessions_with_usage": sum(bool(session["usage_events"]) for session in sessions),
        "usage_complete": bool(sessions) and all(session["usage_events"] for session in sessions),
        "observed_usage": totals or None,
        "observed_failure_signals": signals,
        "final_failure_stage": None if published else "intent" if (run.checkpoint or "").startswith("intent:") else "core_or_execution" if terminal else None,
        "sessions": sessions,
        "boundaries": [
            "Usage is CLI-reported for retained Core sessions; absent usage remains unknown, not zero.",
            "Intent transcripts stored outside the run directory are counted separately by experiment reports.",
            "Observed transport warnings can occur in successful runs and are not terminal failure labels.",
            "Persisted elapsed time measures recorded state lifetime, not a production latency SLA.",
            "File permissions are CLI policy plus post-run audit; this does not establish container-level isolation.",
        ],
    }
