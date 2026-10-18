"""Recompute portfolio claims from source manifests and retained run records.

This collector is read-only with respect to source results and run workspaces.
It does not call a model, repair a candidate or change publication status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from demopilot.models import DemoRun  # noqa: E402
from demopilot.run_metrics import cli_session_metrics, run_metrics  # noqa: E402


def load(path: str | Path) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def published(row: dict[str, Any]) -> bool:
    return row.get("status", "completed") == "completed" and row.get("publication_status") == "published" and row.get("post_publish_audit_status") == "passed" and row.get("browser_status") == "passed"


def group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_count": len(rows),
        "publication_and_known_contract_pass_count": sum(published(row) for row in rows),
        "revision_total": sum(row.get("revision_count", 0) for row in rows),
        "cases_with_revisions": sum(row.get("revision_count", 0) > 0 for row in rows),
        "zero_revision_pass_count": sum(published(row) and row.get("revision_count", 0) == 0 for row in rows),
        "recorded_core_cli_calls": sum(row.get("agent_calls", 0) for row in rows),
        "run_ids": [row["run_id"] for row in rows],
    }


def build_report(paired: Path | None = None, regression: Path | None = None) -> dict[str, Any]:
    sources = {
        "baseline": "evaluation_sets/codex-cli-v1/results/full-real-post-audit-20261006.json",
        "recovery": "evaluation_sets/codex-cli-v1/results/failure-followup-20261007.json",
        "last_recovery": "evaluation_sets/codex-cli-v1/results/failure-followup-replenishment-v3-20261007.json",
        "hard": "docs/engineering/hard-v2-ab/full-real-2026-10-07.json",
        "prompt_pilot": "evaluation_sets/codex-cli-ab-v1/results/pilot-20261008/prompt-ab-pilot-20261008.json",
    }
    baseline = load(sources["baseline"])["results"]
    merged = {row["case_id"]: row for row in baseline}
    for key in ("recovery", "last_recovery"):
        for row in load(sources[key])["results"]:
            if row["case_id"] not in merged:
                raise ValueError("Recovery cannot change the baseline denominator")
            merged[row["case_id"]] = row
    hard = load(sources["hard"])["cases"]
    variants = load(sources["prompt_pilot"])["variants"]
    prompt = {key: group(value["results"]) for key, value in variants.items()}
    report: dict[str, Any] = {
        "schema_version": "demopilot-portfolio-evidence-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline": group(baseline),
        "incremental_recovery": {**group(list(merged.values())), "single_fresh_full_batch": False},
        "hard_v2": {**group(hard), "business_semantics": "generic fixtures; known-contract behavior only"},
        "prompt_pilot": {"variants": prompt, "pair_count": 4, "randomized": False,
                         "meaning": "prompt organization; this is not the seller-interview experiment"},
        "sources": sources,
        "source_sha256": {key: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for key, path in sources.items()},
        "limitations": [
            "Historical scores are reaggregated, not a fresh browser rerun of every old artifact.",
            "Incremental recovery combines baseline successes with subsequent retries and is not causal A/B evidence.",
            "No real customer adoption, conversion, production scale or sales-time saving has been measured.",
            "CLI-reported usage omits sessions without usage records; unknown usage is never zero.",
        ],
    }
    definitions = load("evaluation_sets/codex-cli-v1/cases.json")["cases"]
    missing_files = []
    hash_conflicts = []
    for case in definitions:
        directory = ROOT / "testdata" / case["id"]
        for name in ("inputs.json", "acceptance.json", "manifest.json"):
            if not (directory / name).is_file():
                missing_files.append(str(directory / name))
        if (directory / "manifest.json").is_file():
            for entry in load(directory / "manifest.json").get("files", []):
                path = directory / entry["path"]
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                    hash_conflicts.append(str(path.relative_to(ROOT)))
    report["dataset_audit"] = {
        "definition_count": len(definitions),
        "tiers": dict(Counter(case["difficulty"] for case in definitions)),
        "baseline_case_ids_match": {case["id"] for case in definitions} == {row["case_id"] for row in baseline},
        "missing_required_files": missing_files,
        "manifest_hash_conflicts": hash_conflicts,
        "read_only": True,
    }
    rows = [*baseline, *merged.values(), *hard]
    rows += [row for variant in variants.values() for row in variant["results"]]
    if paired is not None:
        paired_payload = json.loads(paired.read_text(encoding="utf-8"))
        paired_rows = paired_payload["results"]
        report["intent_pilot"] = {"source": str(paired), "all_selected_terminal": paired_payload["all_selected_terminal"], "arms": {}}
        for arm in ("raw-sales", "intent-agent"):
            selected = [row for row in paired_rows if row["arm"] == arm]
            durations = [(datetime.fromisoformat(row["finished_at"]) - datetime.fromisoformat(row["started_at"])).total_seconds() for row in selected]
            intent_sessions = []
            for row in selected:
                trace = paired.parent / row["case_id"] / arm / "intent"
                intent_sessions += [cli_session_metrics(path, paired.parent) for path in sorted(trace.glob("turn-*-stdout.jsonl"))]
            report["intent_pilot"]["arms"][arm] = {
                **group(selected), "final_gate_pass_count": sum(row.get("final_pass", False) for row in selected),
                "intent_cli_calls": sum(row.get("intent_cli_calls", 0) for row in selected),
                "total_cli_calls": sum(row.get("total_cli_calls", 0) for row in selected),
                "seller_answer_release_count": sum(row.get("seller_answers_released", False) for row in selected),
                "median_end_to_end_seconds": round(statistics.median(durations), 3) if durations else None,
                "intent_sessions": intent_sessions,
            }
        audit_path = paired.parent / "external-audit" / "external-business-audit.json"
        if audit_path.exists():
            report["intent_pilot"]["external_business_audit"] = load(audit_path)["metrics"]
        else:
            report["intent_pilot"]["external_business_audit"] = "not_run"
        rows += paired_rows
    if regression is not None:
        regression_rows = json.loads((regression / "results.json").read_text(encoding="utf-8"))["results"]
        report["business_gate_regression"] = {
            **group(regression_rows), "source": str(regression), "not_an_ab_rerun": True,
            "interventions": ["clarified business goals", "full-fixture gates before publication"],
        }
        audit_path = regression / "external-business-audit.json"
        if audit_path.is_file():
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            report["business_gate_regression"].update(
                independent_business_pass_count=audit["business_pass_count"],
                independent_journey_count=sum(row.get("journey_count", 0) for row in audit["rows"]),
            )
        rows += regression_rows
    run_ids = sorted({row["run_id"] for row in rows})
    records = []
    missing = []
    mismatches = []
    for run_id in run_ids:
        directory = ROOT / ".data" / "runs" / run_id
        if not (directory / "run.json").is_file():
            missing.append(run_id)
            continue
        run = DemoRun.model_validate_json((directory / "run.json").read_text(encoding="utf-8"))
        records.append(run_metrics(run, directory))
        for row in rows:
            if row["run_id"] == run_id and row["publication_status"] != run.publication_status:
                mismatches.append({"run_id": run_id, "manifest": row["publication_status"], "record": run.publication_status})
    report["run_evidence_audit"] = {"referenced_run_count": len(run_ids), "readable_run_count": len(records), "missing_run_ids": missing, "manifest_state_mismatches": mismatches}
    report["run_metrics"] = records
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/portfolio-v1/evidence")
    parser.add_argument("--paired-results", type=Path)
    parser.add_argument("--regression-dir", type=Path)
    args = parser.parse_args()
    report = build_report(args.paired_results, args.regression_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / "portfolio-evidence.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(target), "baseline": report["baseline"]["publication_and_known_contract_pass_count"], "incremental_recovery": report["incremental_recovery"]["publication_and_known_contract_pass_count"], "hard_v2": report["hard_v2"]["publication_and_known_contract_pass_count"], "run_audit": report["run_evidence_audit"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
