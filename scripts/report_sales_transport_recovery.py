"""Read-only comparison of sealed23/40 and the separately authorized17 recovery."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from report_sales_benchmark_pilot import audit_cost, read, report

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".data/sales-benchmark-v3/validation-40-20261019-v4"
FIELDS = ("model", "reasoning_effort", "cli_timeout_seconds", "core_call_cap",
          "intake_call_cap", "max_parallel", "case_deadline_seconds", "dataset_manifest_sha256")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate(rows, root):
    costs = [audit_cost(root / "sales-core/sessions" / r["session_id"]) for r in rows]
    return dict(tasks=len(rows), delivered=sum(r["delivery_pass"] for r in rows),
        published=sum(r["status"] == "published" for r in rows),
        published_defects=sum(r["status"] == "published" and not r["final_functional_pass"] for r in rows),
        failure_stages=dict(Counter(r["stage"] for r in rows if not r["delivery_pass"])),
        browser_paths={k: sum(r["independent_check"][k] for r in rows) for k in ("planned", "executed", "passed")},
        exact_http_assets=sum(len(r.get("exact_served_assets", [])) for r in rows),
        calls=sum(c["calls"] for c in costs), intake=sum(c["intake"] for c in costs), core=sum(c["core"] for c in costs),
        internal_core_repairs=sum(r.get("internal_core_repairs", 0) for r in rows),
        usage_complete=sum(c["usage_complete"] for c in costs), missing_usage=sum(c["missing_usage"] for c in costs),
        failed_root_calls=sum(c["failed_root_calls"] for c in costs),
        tokens={k: sum(c["tokens"][k] for c in costs) for k in ("input_tokens", "cached_input_tokens", "output_tokens")},
        sum_task_seconds=round(sum(r["elapsed_seconds"] for r in rows), 2), monetary_cost=None)


def build(output, destination):
    old = read(BASELINE / "results.json")
    assert sha(BASELINE / "results.json") == "2ea694d11c1082ee1b524e108f6989ebe6433f6cfa05cdbda1db9003c2ac6f82"
    raw, context, baseline_context = read(output / "results.json"), read(output / "context.json"), read(BASELINE / "context.json")
    failed = sorted(r["case_id"] for r in old["rows"] if not r["delivery_pass"])
    assert context["cohort_kind"] == "transport-recovery" and sorted(context["pilot_ids"]) == failed
    assert sorted(r["case_id"] for r in raw["rows"]) == failed and len(raw["rows"]) == 17
    assert all(context[k] == baseline_context[k] for k in FIELDS)
    assert raw["summary"]["terminal"] == 17
    preflight = read(destination / "preflight.json")
    assert all(sha(ROOT / p) == digest for p, digest in preflight["protected_sha256"].items())
    heldout = set(read(ROOT / "evaluation_sets/sales-benchmark-v3/split.json")["heldout"])
    assert not heldout.intersection(context["pilot_ids"])
    before_rows = [r for r in old["rows"] if r["case_id"] in failed]
    before, after = aggregate(before_rows, BASELINE), aggregate(raw["rows"], output)
    power = read(output.with_name(output.name + "-power.json"))
    wall = (datetime.fromisoformat(power["finished_at"]) - datetime.fromisoformat(power["started_at"])).total_seconds()
    diagnoses = [ROOT / ".data/sales-benchmark-v3" / n / "results.json" for n in (
        "transport-readiness-20261019-v5", "transport-readiness-final-20261019-v5", "transport-readiness-http-20261019-v6")]
    probes = [read(p) for p in diagnoses]
    diagnostics = dict(calls=sum(p["cost"]["cli_process_calls"] for p in probes),
        calls_with_usage=sum(p["cost"]["calls_with_reported_usage"] for p in probes),
        elapsed_seconds=round(sum(p["elapsed_seconds"] for p in probes), 2),
        tokens={k: sum(p["cost"]["reported_root_tokens"][k] for p in probes) for k in ("input_tokens", "cached_input_tokens", "output_tokens")})
    aborted_root = ROOT / ".data/sales-benchmark-v3/transport-recovery-17-20261019-v5"
    aborted_rows = read(aborted_root / "terminal-results.json")["rows"]
    aborted_costs = [audit_cost(aborted_root / "sales-core/sessions" / r["session_id"]) for r in aborted_rows]
    aborted_power = read(aborted_root.with_name(aborted_root.name + "-power.json"))
    aborted = dict(tasks=len(aborted_rows), published=sum(r["status"] == "published" for r in aborted_rows),
        calls=sum(c["calls"] for c in aborted_costs), calls_with_usage=sum(c["usage_complete"] for c in aborted_costs),
        missing_usage=sum(c["missing_usage"] for c in aborted_costs),
        tokens={k: sum(c["tokens"][k] for c in aborted_costs) for k in ("input_tokens", "cached_input_tokens", "output_tokens")},
        wall_seconds=round((datetime.fromisoformat(aborted_power["finished_at"]) - datetime.fromisoformat(aborted_power["started_at"])).total_seconds(), 2),
        final_browser_status="aborted_missing_browser_in_wrong_system_python", planned_paths=115, executed_paths=0,
        cause="Initial preflight omitted original Python/browser and short CLI success did not establish sustained transport. All terminal traces and cost retained; never replace with final recovery.")
    transport_events = []
    for path in output.rglob("stdout.jsonl"):
        for line in path.read_text("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") in {"error", "turn.failed"}:
                transport_events.append(dict(trace=path.relative_to(output).as_posix(), type=event["type"], message=event.get("message") or event.get("error")))
    report(output, destination / "recovery-17")
    result = dict(schema_version="sales-v3-transport-recovery-v1", created_at=datetime.now(UTC).isoformat(),
        original_first40=dict(delivered=23, planned=40, percentage=57.5, unchanged=True, summary=old["summary"]),
        same_failed17=dict(before=before, after=after, recovered=after["delivered"]),
        incremental_coverage=dict(delivered=23 + after["delivered"], planned=40, clean_full40_rerun=False,
                                  caveat="Original23 retained; only17 rerun, not a clean40 benchmark or intent causal gain."),
        diagnostics=diagnostics, aborted_v5=aborted,
        recovery_wall_seconds=round(wall, 2), heartbeat_gaps=power["heartbeat_gaps"],
        recovery_cli_error_events=transport_events,
        total_new_root_calls=diagnostics["calls"] + aborted["calls"] + after["calls"],
        model_budget_data_unchanged={k: context[k] for k in FIELDS},
        business_runtime_boundary=read(destination / "source-boundary.json"),
        protected_original_sha256=preflight["protected_sha256"],
        raw_evidence_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in [BASELINE/"results.json", BASELINE/"context.json", output/"results.json", output/"context.json", output.with_name(output.name + "-power.json"), aborted_root/"terminal-results.json", aborted_root/"context.json", aborted_root.with_name(aborted_root.name + "-power.json"), *diagnoses]},
        heldout_executed=0,
        inference_limit="Proxy logs locate unreachable outbound gateway; original WebSocket TLS failed then fell backHTTP. Official HTTPS/SSE transport configured locally. No proof of permanent upstream repair; no global proxy/account/model/credential edits.",
        cost_limit="Cached input is included in input. Missingusage is unknown, not zero. RootCLI reports may omit native-child usage; no monetary bill.")
    destination.mkdir(parents=True, exist_ok=True)
    (destination/"comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(before=before, after=after, diagnostics=diagnostics, wall=round(wall, 2)), ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.destination.resolve())
