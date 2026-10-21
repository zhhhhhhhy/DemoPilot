"""Explicit regression of the already observed first15, never the remaining85.

Selection derives from the immutable original campaign and terminal records.
The original campaign remains stopped. This separate run never replaces13/15
and is no longer an unseen final-set generalization measurement.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from sales_final_campaign import BUDGET, DATASET, ROOT, read, sha, sources
from sales_final_campaign import PLAN as BASELINE_PLAN

PLAN = ROOT / "docs/sales-benchmark-v3/observed15-rerun-20261021/PLAN.json"
OUTPUT = ROOT / ".data/sales-benchmark-v3/observed15-rerun-20261021-v1"
BASELINE_PLAN_SHA256 = "ff5f27669cda0d4c9652c3ec9fcb71412ef7fd1fa3b87f74e4293bfbf75d7663"


def original_records():
    if sha(BASELINE_PLAN) != BASELINE_PLAN_SHA256:
        raise ValueError("Original stopped campaign changed")
    original = read(BASELINE_PLAN)
    records = []
    for batch in original["batches"][:2]:
        result_path = ROOT / batch["output"] / "results.json"
        context_path = result_path.parent / "context.json"
        result, context = read(result_path), read(context_path)
        if ({r["case_id"] for r in result["rows"]} != set(batch["ids"])
                or result["summary"]["terminal"] != len(batch["ids"])
                or any(context.get(k) != v for k, v in BUDGET.items())):
            raise ValueError("Original batch incomplete or budget differs")
        records.append(dict(ids=batch["ids"], results=result_path.relative_to(ROOT).as_posix(),
                            results_sha256=sha(result_path), context=context_path.relative_to(ROOT).as_posix(),
                            context_sha256=sha(context_path),
                            delivered=sum(bool(r["delivery_pass"]) for r in result["rows"])))
    return original, records


def validate_selection(plan, original, split, model):
    expected = [i for batch in original["batches"][:2] for i in batch["ids"]]
    selected = plan.get("ids", [])
    if (plan.get("schema_version") != "observed-final15-regression-v1"
            or len(selected) != len(set(selected)) or len(selected) != 15
            or selected != expected or not set(selected).issubset(split["heldout"])
            or set(selected) & (set(split["development"]) | set(split["validation"]))):
        raise ValueError("Only the exact original observed15 in original order may run; remaining85 locked")
    if plan.get("budget") != original["budget"] or plan["budget"] != BUDGET or model != BUDGET["model"]:
        raise ValueError("Original model and every budget must remain unchanged")
    if plan.get("original_delivered") != 13 or plan.get("remaining_unexecuted") != 85:
        raise ValueError("Preserve original13/15 and unrun85")


def verify(plan):
    original, records = original_records()
    validate_selection(plan, original, read(DATASET / "split.json"), plan["budget"]["model"])
    if records != plan["original_batches"]:
        raise ValueError("Original13/15 evidence changed")
    if sources() != plan["source_sha256"]:
        raise ValueError("Frozen rerun source changed; no further model launches")
    if sha(DATASET / "manifest.json") != plan["dataset_manifest_sha256"]:
        raise ValueError("Original data manifest changed")
    if any(not (ROOT / p).is_file() or sha(ROOT / p) != h
           for p, h in read(DATASET / "manifest.json")["files"].items()):
        raise ValueError("Original data or acceptance file changed")
    # A separate regression never creates or resumes any later original batch.
    if any((ROOT / b["output"]).exists() for b in original["batches"][2:]):
        raise ValueError("Remaining85 must stay unstarted")


def unlock(plan_path, model, output):
    if not plan_path or Path(plan_path).resolve() != PLAN.resolve():
        raise ValueError("Observed15 rerun requires its explicit exact authorization plan")
    plan = read(PLAN)
    if model != plan["budget"]["model"]:
        raise ValueError("Original model cannot change")
    if Path(output).resolve() != OUTPUT.resolve():
        raise ValueError("Rerun must use its separate original fresh output directory")
    if Path(output, "context.json").exists():
        raise ValueError("Never overwrite or relaunch a started rerun")
    verify(plan)
    return list(plan["ids"]), dict(plan=PLAN.relative_to(ROOT).as_posix(), plan_sha256=sha(PLAN),
                                  original_score="13/15", remaining_unexecuted=85,
                                  boundary="Previously observed15 regression, not additional unseen final cases or isolated intent-method causal evidence.")


def create():
    if PLAN.exists() or OUTPUT.exists():
        raise FileExistsError("Preserve existing rerun plan/output")
    original, records = original_records()
    plan = dict(schema_version="observed-final15-regression-v1", created_at=datetime.now(UTC).isoformat(),
                authorization="User explicitly requested complete new-version replay of original15, same data/model/budget/standards; preserve13/15 and do not run remaining85,2026-10-21.",
                ids=[i for b in original["batches"][:2] for i in b["ids"]],
                original_delivered=sum(r["delivered"] for r in records), remaining_unexecuted=85,
                original_batches=records, original_plan=BASELINE_PLAN.relative_to(ROOT).as_posix(),
                original_plan_sha256=sha(BASELINE_PLAN), budget=dict(original["budget"]),
                dataset_manifest_sha256=sha(DATASET / "manifest.json"), source_sha256=sources(),
                output=OUTPUT.relative_to(ROOT).as_posix(),
                scoring="All15 to terminal then fresh real Chromium by original seller facts; new checker covers omitted existing requirements. No final-score feedback, app edits or second chance.",
                change_boundary="Use current shared business-field/capability mechanism and strengthened original-contract checks; no production business edits for this rerun.",
                stop_policy="Finish the authorized15 once within original per-case caps. Never unlock85; retain all final failures without rescoring a repaired version.")
    verify(plan)
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    import json
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(dict(plan=PLAN.relative_to(ROOT).as_posix(), ids=plan["ids"], budget=plan["budget"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", required=True)
    parser.parse_args()
    create()
