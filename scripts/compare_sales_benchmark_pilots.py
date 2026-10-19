"""Compare two completed same20 pilots without launching models or changing scores."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET_KEYS = (
    "model",
    "reasoning_effort",
    "cli_timeout_seconds",
    "core_call_cap",
    "intake_call_cap",
    "max_parallel",
    "case_deadline_seconds",
)


def read(path):
    return json.loads(path.read_text("utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(row):
    if row["delivery_pass"]:
        return "delivered"
    if row["status"] == "published" and not row["final_functional_pass"]:
        return "published_functional_defect"
    if row["status"] == "published":
        return "published_resource_mismatch"
    if row.get("final_functional_pass"):
        return "correct_but_hidden"
    return row["stage"]


def wall(cohort):
    power = read(cohort.with_name(cohort.name + "-power.json"))
    assert power["status"] == "completed", "Cohort process has not finished"
    end_key = "finished_at" if "finished_at" in power else "ended_at"
    seconds = (
        datetime.fromisoformat(power[end_key])
        - datetime.fromisoformat(power["started_at"])
    ).total_seconds()
    return {"seconds": round(seconds, 2), "heartbeat_gaps": power["heartbeat_gaps"]}


def measures(report, cohort):
    s, rows = report["summary"], report["cases"]
    raw = read(cohort / "results.json")
    successes = [r["elapsed_seconds"] for r in rows if r["delivery_pass"]]
    delivered = s["delivered"]
    tokens = s["reported_root_tokens"]
    return {
        "planned": len(rows),
        "delivered": delivered,
        "published": s["published"],
        "delivery_rate": delivered / len(rows),
        "terminal_stages": dict(Counter(stage(r) for r in rows)),
        "core_reached": sum(r["cost"]["core"] > 0 for r in rows),
        "published_defects": s["published_defects"],
        "root_cli_calls": s["root_cli_calls"],
        "intake_calls": s["intake_calls"],
        "core_calls": s["core_calls"],
        "internal_core_repairs": sum(r.get("internal_core_repairs") or 0 for r in rows),
        "calls_with_reported_usage": s["calls_with_reported_usage"],
        "reported_root_tokens": tokens,
        "task_elapsed_median_seconds": round(
            statistics.median(r["elapsed_seconds"] for r in rows), 2
        ),
        "successful_task_elapsed_median_seconds": round(statistics.median(successes), 2)
        if successes
        else None,
        "successful_task_elapsed_seconds": sorted(successes),
        "sum_task_elapsed_seconds": s["sum_elapsed_seconds"],
        "wall": wall(cohort),
        "final_browser_paths": s["final_browser_paths"],
        "exact_served_assets": sum(
            len(r.get("exact_served_assets", [])) for r in raw["rows"]
        ),
        "observed_input_flags": raw["summary"].get("observed_input_flags"),
        "per_delivered": {
            "root_cli_calls": round(s["root_cli_calls"] / delivered, 2)
            if delivered
            else None,
            "input_tokens": round(tokens["input_tokens"] / delivered, 2)
            if delivered
            else None,
            "output_tokens": round(tokens["output_tokens"] / delivered, 2)
            if delivered
            else None,
        },
        "monetary_cost": None,
    }


def compare(args):
    old, new = read(args.baseline_report), read(args.rerun_report)
    a, b = read(args.baseline / "context.json"), read(args.rerun / "context.json")
    ids = read(ROOT / "evaluation_sets/sales-benchmark-v3/pilot-20.json")["case_ids"]
    split = read(ROOT / "evaluation_sets/sales-benchmark-v3/split.json")
    assert a["pilot_ids"] == b["pilot_ids"] == ids and len(set(ids)) == 20
    assert not b.get("targeted_regression") and not set(ids) & set(split["heldout"])
    assert all(a[k] == b[k] for k in BUDGET_KEYS), "Model/budget drift"
    assert a["dataset_manifest_sha256"] == b["dataset_manifest_sha256"]
    for report in (old, new):
        assert len(report["cases"]) == 20 and {
            r["case_id"] for r in report["cases"]
        } == set(ids)
    old_by_id = {r["case_id"]: r for r in old["cases"]}
    paired = []
    for row in sorted(new["cases"], key=lambda r: r["case_id"]):
        previous = old_by_id[row["case_id"]]
        transition = (
            ("both_pass" if previous["delivery_pass"] else "improved")
            if row["delivery_pass"]
            else ("regressed" if previous["delivery_pass"] else "both_fail")
        )
        paired.append(
            {
                "case_id": row["case_id"],
                "difficulty": row["difficulty"],
                "family": row["family"],
                "before": stage(previous),
                "after": stage(row),
                "transition": transition,
                "before_calls": previous["cost"]["calls"],
                "after_calls": row["cost"]["calls"],
                "after_failure_reason": row.get("failure_reason"),
            }
        )
    before, after = measures(old, args.baseline), measures(new, args.rerun)
    integrity = {}
    for label, manifest_path in [
        ("v3", ROOT / "evaluation_sets/sales-benchmark-v3/manifest.json"),
        (
            "historical_v2",
            ROOT / "evaluation_sets/quotation-reliability-v2/manifest.json",
        ),
    ]:
        manifest = read(manifest_path)
        files = manifest["files"]
        # Historical manifest wraps paths/hashes in a different schema.
        if isinstance(files, list):
            files = {item["path"]: item["sha256"] for item in files}
        mismatches = [
            p for p, h in files.items() if not (ROOT / p).exists() or sha(ROOT / p) != h
        ]
        assert not mismatches, f"Frozen {label} inputs changed: {mismatches}"
        integrity[label] = {
            "files": len(files),
            "mismatches": mismatches,
            "manifest_sha256": sha(manifest_path),
        }
    preflight = read(args.destination / "preflight.json")
    protected = preflight["protected_original_sha256"]
    assert all(sha(ROOT / p) == h for p, h in protected.items()), (
        "Original results modified"
    )
    corrected = read(
        ROOT / ".data/sales-benchmark-v3/pilot-regression-20261019-v2/context.json"
    )
    assert b["code_sha256"] == corrected["code_sha256"], "Not the repaired version"
    changed_source = sorted(
        k
        for k in set(a["code_sha256"]) | set(b["code_sha256"])
        if a["code_sha256"].get(k) != b["code_sha256"].get(k)
    )
    result = {
        "schema_version": "sales-v3-paired-full20-replay-v1",
        "before": before,
        "after": after,
        "absolute_gain_percentage_points": round(
            100 * (after["delivery_rate"] - before["delivery_rate"]), 2
        ),
        "additional_delivered": after["delivered"] - before["delivered"],
        "transitions": dict(Counter(r["transition"] for r in paired)),
        "paired": paired,
        "by_difficulty": {
            d: {
                "planned": sum(r["difficulty"] == d for r in paired),
                "before_delivered": sum(
                    r["difficulty"] == d and r["before"] == "delivered" for r in paired
                ),
                "after_delivered": sum(
                    r["difficulty"] == d and r["after"] == "delivered" for r in paired
                ),
            }
            for d in ("simple", "medium", "hard")
        },
        "fixed_budget": {k: b[k] for k in BUDGET_KEYS},
        "changed_runtime_source": changed_source,
        "protected_original_sha256": protected,
        "input_integrity": integrity,
        "heldout_model_executed": 0,
        "validation_model_executed": 0,
        "anomalies_live_executed": 0,
        "evidence_hashes": {
            str(p.relative_to(ROOT)).replace("\\", "/"): sha(p)
            for p in (
                args.baseline / "results.json",
                args.rerun / "results.json",
                args.baseline_report,
                args.rerun_report,
            )
        },
        "boundary": "Same known20 development replay, one sample per case/version; two integration fixes jointly tested. No blind generalization, pure-prompt effect, production-sales rate or monetary saving claim. Root CLI tokens may omit native-child usage. Cached input is included in input tokens.",
    }
    args.destination.mkdir(parents=True, exist_ok=True)
    (args.destination / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "before",
                    "after",
                    "absolute_gain_percentage_points",
                    "transitions",
                    "by_difficulty",
                    "changed_runtime_source",
                    "input_integrity",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--rerun", required=True, type=Path)
    parser.add_argument("--baseline-report", required=True, type=Path)
    parser.add_argument("--rerun-report", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    for key in ("baseline", "rerun", "baseline_report", "rerun_report", "destination"):
        setattr(args, key, getattr(args, key).resolve())
    compare(args)
