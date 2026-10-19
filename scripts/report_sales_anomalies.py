"""Summarize retained anomaly runs without modifying their original results."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "backend/src")]
from demopilot.quotation_loop import write_json
from run_sales_benchmark_pilot import trace_cost


def read(path):
    return json.loads(path.read_text("utf8"))


def summary_cost(directory):
    value = trace_cost(directory)
    return {
        k: value[k]
        for k in (
            "cli_process_calls",
            "calls_with_reported_usage",
            "calls_without_reported_usage",
            "reported_root_tokens",
            "monetary_cost",
        )
    }


def main(args):
    baseline = read(args.baseline / "results.json")
    first = read(args.retest / "results.json")
    final = read(args.final / "results.json")
    positive = read(args.positive / "results.json")
    qualification = read(
        ROOT
        / "docs/sales-benchmark-v3/anomaly-validation/intent-retest-independent-qualification.json"
    )
    assert baseline["terminal"] == baseline["planned"] == 40
    assert sorted(int(r["case_id"].rsplit("-", 1)[1]) for r in first["rows"]) == [
        11,
        12,
        13,
        14,
        15,
        27,
        37,
        39,
        40,
    ]
    assert sorted(r["case_id"] for r in final["rows"]) == ["sales-v3-anomaly-39", "sales-v3-anomaly-40"]
    assert qualification["passed"] is True
    originals = read(
        ROOT / "docs/sales-benchmark-v3/anomaly-validation/baseline-score.json"
    )
    assert (
        hashlib.sha256((args.baseline / "results.json").read_bytes()).hexdigest()
        == originals["baseline_result_sha256"]
    )
    current = {
        r["case_id"]: dict(
            passed=r["passed"],
            evidence=str(
                args.baseline / "cases" / r["case_id"].rsplit("-", 1)[1] / "result.json"
            ),
        )
        for r in baseline["rows"]
    }
    current["sales-v3-anomaly-37"]["passed"] = False
    for directory, result in ((args.retest, first), (args.final, final)):
        for row in result["rows"]:
            current[row["case_id"]] = dict(
                passed=row["passed"],
                evidence=str(
                    directory
                    / "cases"
                    / row["case_id"].rsplit("-", 1)[1]
                    / "result.json"
                ),
            )
    batches = []
    for label, directory, result in (
        ("baseline40", args.baseline, baseline),
        ("targeted9", args.retest, first),
        ("remaining39-40", args.final, final),
    ):
        batches.append(
            dict(
                name=label,
                planned=result["planned"],
                passed=result["passed"],
                elapsed_seconds=result["elapsed_seconds"],
                cost=summary_cost(directory),
            )
        )
    diagnostics = [
        dict(
            directory=str(d),
            passed=read(d / "results.json")["passed"],
            elapsed_seconds=read(d / "results.json")["elapsed_seconds"],
            cost=summary_cost(d),
        )
        for d in args.diagnostics
    ]
    control = dict(summary=positive["summary"], cost=summary_cost(args.positive))
    all_costs = (
        [b["cost"] for b in batches]
        + [b["cost"] for b in diagnostics]
        + [control["cost"]]
    )
    totals = {
        k: sum(c[k] for c in all_costs)
        for k in (
            "cli_process_calls",
            "calls_with_reported_usage",
            "calls_without_reported_usage",
        )
    }
    totals["reported_root_tokens"] = {
        k: sum(c["reported_root_tokens"][k] for c in all_costs)
        for k in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    totals["monetary_cost"] = None
    result = dict(
        schema_version="anomaly40-retained-comparison-v1",
        baseline=dict(
            automated=baseline["passed"],
            strict=originals["strict_passed"],
            denominator=40,
        ),
        batches=batches,
        diagnostics=diagnostics,
        positive_control=control,
        cumulative_covered_passed=sum(r["passed"] for r in current.values()),
        cumulative_denominator=40,
        cumulative_rows=current,
        heldout_executed=0,
        cost_total=totals,
        improvement_boundary="Incremental recovery of fixed anomalies, not a clean new-version full40 rerun or model/intent causal accuracy.27 was a measurement-scope error.40 required an additional callback repair.",
        security_boundary="Synthetic canaries and observed root tool events only; no real credential reads, real final answers or OS/native-child isolation claim.",
        cost_boundary="Historical fixture generation excluded from new cost. Root usage can omit native children. Missing usage is unknown, not zero; no currency bill.",
        process_boundary="One route-gate ordering deviation retained in process-deviation.json; local controller audit does not erase it.",
    )
    write_json(args.output / "comparison.json", result)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                in (
                    "baseline",
                    "cumulative_covered_passed",
                    "cumulative_denominator",
                    "cost_total",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "retest", "final", "positive", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--diagnostics", nargs="+", type=Path, required=True)
    main(p.parse_args())
