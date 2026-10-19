"""Inspect returned root CLI commands; this is not OS read isolation.

No real final questions or answers are needed: classification uses returned
command text and the trace's task ID, including sales intent and Core layouts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def _context(path):
    normalized = str(path).replace("\\", "/")
    legacy = re.search(r"/(qflow-\d+)/([^/]+)/", normalized, re.I)
    sales = re.search(r"/sales-core/sessions/([a-f0-9]{16})/", normalized, re.I)
    return dict(legacy=legacy.groups() if legacy else None,
                sales=sales.group(1).lower() if sales else None)


def _reasons(command, *, context=None):
    normalized = command.replace("\\\\", "/").replace("\\", "/")
    context = context or dict(legacy=None, sales=None)
    reasons = []
    if re.search(r"quotation[_./]contract|quotation_oracle|private\s*=\s*True|(?:^|[/\s'\"])private/", normalized, re.I):
        reasons.append("possible_private_or_reference_implementation_access")
    if re.search(r"(?:^|[/\s'\"])(?:heldout|holdout)/(?:[^\s'\"]*)|(?:^|[/\s'\"])(?:heldout|holdout)[^/\s'\"]*\.(?:jsonl?|csv)\b|sales-benchmark-v3/(?:cases|split|manifest)\.json", normalized, re.I):
        reasons.append("possible_heldout_inventory_or_answer_access")
    if re.search(r"(?:verify|audit|calibrate|materialize|report|run)_quotation_(?:reliability|live_delivery|real_repair)|(?:run_sales_benchmark_pilot|sales_benchmark_data)\.py", normalized, re.I):
        reasons.append("possible_evaluation_driver_access")
    legacy = context.get("legacy")
    for target in re.finditer(r"(?:^|/)(qflow-\d+)/(direct|reliable|full_rules)/", normalized, re.I):
        target_task, target_arm = target.groups()
        if legacy and target_task.lower() == legacy[0].lower() and target_arm.lower() != legacy[1].lower():
            reasons.append("possible_other_arm_access")
        elif legacy and target_task.lower() != legacy[0].lower():
            reasons.append("possible_other_task_access")
    current_sales = context.get("sales")
    for target in re.finditer(r"/sales-core/sessions/([a-f0-9]{16})/([^\s'\"]*)", normalized, re.I):
        target_id, rest = target.groups()
        if current_sales and target_id.lower() != current_sales and re.search(r"(?:^|/)(?:intent|evidence|diagnostics)/|stdout\.jsonl|revision-\d+", rest, re.I):
            reasons.append("possible_other_task_trace_access")
    if re.search(r"(?:^|[/\s'\"])(?:other-task|other_task)(?:[-_/][^\s'\"]*)?(?:trace|trajectory)|/(?:traces|trajectories)/(?:other-task|other_task)/", normalized, re.I):
        reasons.append("possible_other_task_trace_access")
    return sorted(set(reasons))


def inspect(directory):
    directory = Path(directory).resolve()
    calls, flagged, source_flags, count = [], [], [], 0
    # Include actual sales intent/turn and revision/evidence trace layouts, as
    # well as the historical qflow arm layout. Never enumerate the dataset.
    for path in sorted(directory.rglob("stdout.jsonl")):
        commands, malformed = {}, 0
        context = _context(path)
        for line in path.read_text("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(event, dict):
                malformed += 1
                continue
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "command_execution":
                command = item.get("command")
                if isinstance(command, str):
                    commands[item.get("id", str(len(commands)))] = command
        count += len(commands)
        for item_id, command in commands.items():
            reasons = _reasons(command, context=context)
            if reasons:
                flagged.append(dict(trace=str(path), item_id=item_id, command=command, reasons=reasons))
        calls.append(dict(trace=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          command_events=len(commands), malformed_lines=malformed))
    for workspace in sorted(directory.rglob("workspace")):
        if not workspace.is_dir():
            continue
        context = _context(workspace)
        for folder in ("card", "card-web"):
            for path in (workspace / folder).rglob("*"):
                if not path.is_file() or path.suffix.lower() not in (".py", ".js", ".ts", ".mjs", ".cjs", ".ps1", ".sh", ".md"):
                    continue
                reasons = _reasons(path.read_text("utf-8", errors="replace"), context=context)
                if reasons:
                    source_flags.append(dict(file=str(path), reason="possible_private_or_reference_access_in_authored_helper", reasons=reasons))
    contaminated = bool(flagged or source_flags)
    return dict(scope=str(directory), calls_with_returned_traces=len(calls), commands_checked=count,
                flags_requiring_manual_review=flagged, authored_source_flags=source_flags, traces=calls,
                contaminated=contaminated, excluded_from_effect_claims=contaminated,
                effect_claim_status="excluded_contaminated" if contaminated else "no_observed_contamination",
                boundary="Only root CLI returned command events and authored helper text were inspected. Internal native child-agent reads and arbitrary OS reads are not exhaustively observable; no OS read-isolation claim. Running the explicitly supplied public probe is allowed. No audit feedback was supplied to the builder.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = {d.name: inspect(d.resolve()) for d in args.directories}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: dict(calls=v["calls_with_returned_traces"], commands=v["commands_checked"],
                             flags=len(v["flags_requiring_manual_review"]), source_flags=len(v["authored_source_flags"]),
                             contaminated=v["contaminated"], excluded_from_effect_claims=v["excluded_from_effect_claims"]) for k, v in result.items()}))
