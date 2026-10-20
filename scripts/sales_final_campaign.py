"""Explicitly authorized fixed-version final100 campaign, first5 then10.

This module opens no model connections and never changes product business rules.
Only the current batch can be executed; a failed/incomplete batch blocks the next.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation_sets/sales-benchmark-v3"
PLAN = ROOT / "docs/sales-benchmark-v3/final-staged/CAMPAIGN.json"
RUN_ROOT = ROOT / ".data/sales-benchmark-v3/final-staged-20261020"
BUDGET = dict(model="gpt-6.1-sol", reasoning_effort="medium", cli_timeout_seconds=300,
              intake_call_cap=3, core_call_cap=3, max_parallel=2, case_deadline_seconds=2100)


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    files = []
    for name in ("backend/src", "frontend/src", "frontend/dist", "scripts"):
        files.extend(p for p in (ROOT / name).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)}


def schedule(metadata):
    groups = defaultdict(lambda: defaultdict(list))
    for case in metadata:
        groups[case["difficulty"]][case["family"]].append(case["id"])
    pools = {}
    for difficulty, families in groups.items():
        queues = [deque(sorted(items)) for _, items in sorted(families.items())]
        pool = []
        while any(queues):
            for queue in queues:
                if queue:
                    pool.append(queue.popleft())
        pools[difficulty] = deque(pool)
    pattern = ("simple", "medium", "hard", "medium", "simple", "hard", "medium", "simple", "hard", "medium")
    ordered = []
    while any(pools.values()):
        for difficulty in pattern:
            if pools.get(difficulty):
                ordered.append(pools[difficulty].popleft())
    return [ordered[:5], *[ordered[i:i + 10] for i in range(5, len(ordered), 10)]]


def validate_plan(plan, split, model):
    ordered = [identifier for b in plan["batches"] for identifier in b["ids"]]
    if (plan.get("schema_version") != "authorized-final100-staged-v1"
            or len(ordered) != 100 or len(set(ordered)) != 100
            or set(ordered) != set(split["heldout"])
            or set(ordered) & (set(split["development"]) | set(split["validation"]))):
        raise ValueError("Final campaign must contain exact disjoint original100, once each")
    if [len(b["ids"]) for b in plan["batches"]] != [5, *([10] * 9), 5]:
        raise ValueError("Frozen progressive sizes must be5, then10, final5")
    if plan.get("budget") != BUDGET or model != BUDGET["model"]:
        raise ValueError("Original model and budgets cannot change")


def require_complete_pass(result, ids):
    rows, summary = result.get("rows", []), result.get("summary", {})
    if (len(rows) != len(ids) or {r["case_id"] for r in rows} != set(ids)
            or summary.get("terminal") != len(ids) or summary.get("planned") != len(ids)):
        raise ValueError("Previous batch is incomplete; do not launch a later batch")
    if (any(not r.get("delivery_pass") or not r.get("final_functional_pass") for r in rows)
            or summary.get("published_functional_defects", 0)
            or summary.get("observed_input_flags", 0)):
        raise ValueError("Previous batch failed or needs input-audit review; stop campaign without repair")


def verify_sources(plan):
    if sources() != plan["source_sha256"]:
        raise ValueError("Frozen final campaign source changed; no further model launches")
    if sha(DATASET / "manifest.json") != plan["dataset_manifest_sha256"]:
        raise ValueError("Frozen final dataset manifest changed")


def unlock(plan_path, batch_index, model, output):
    if not plan_path or Path(plan_path).resolve() != PLAN.resolve():
        raise ValueError("Heldout requires this authorized campaign's exact plan path")
    plan = read(PLAN)
    validate_plan(plan, read(DATASET / "split.json"), model)
    verify_sources(plan)
    if not isinstance(batch_index, int) or not 1 <= batch_index <= len(plan["batches"]):
        raise ValueError("A valid fixed batch index is required")
    batch = plan["batches"][batch_index - 1]
    if Path(output).resolve() != (ROOT / batch["output"]).resolve():
        raise ValueError("Batch must use its original fresh output directory")
    previous = []
    for earlier in plan["batches"][:batch_index - 1]:
        base = ROOT / earlier["output"]
        if not (base / "results.json").is_file():
            raise ValueError("Previous batch is incomplete; do not launch a later batch")
        context = read(base / "context.json")
        if context.get("final_campaign", {}).get("plan_sha256") != sha(PLAN):
            raise ValueError("Previous batch belongs to a different frozen campaign")
        require_complete_pass(read(base / "results.json"), earlier["ids"])
        previous.append(dict(batch=earlier["index"], result_sha256=sha(base / "results.json")))
    if (Path(output) / "context.json").exists():
        raise ValueError("Never overwrite or relaunch a started final batch")
    return list(batch["ids"]), dict(plan=PLAN.relative_to(ROOT).as_posix(), plan_sha256=sha(PLAN),
                                   batch_index=batch_index, previous=previous,
                                   authorized_total=100, current_batch_size=len(batch["ids"]))


def create():
    if PLAN.exists():
        raise FileExistsError("Preserve existing final campaign; never regenerate the order")
    split = read(DATASET / "split.json")
    # Use pre-existing split/difficulty/family metadata only, never gold outcomes.
    metadata = [{k: c[k] for k in ("id", "difficulty", "family")}
                for c in read(DATASET / "cases.json")["cases"] if c["id"] in split["heldout"]]
    old = read(ROOT / "docs/sales-benchmark-v3/anomaly-repair-rerun/comparison.json")
    if old["full40"]["strict_passed"] != 40:
        raise ValueError("Formal final campaign requires the verified40/40 reliability checkpoint")
    previous_product = read(ROOT / ".data/sales-benchmark-v3/anomaly40-full-rerun-20261020-v6/context.json")["product_sources"]
    if any(sha(ROOT / path) != digest for path, digest in previous_product.items()):
        raise ValueError("Product differs from the accepted reliability checkpoint")
    batches = [dict(index=n, ids=ids, output=(RUN_ROOT / f"batch-{n:02}").relative_to(ROOT).as_posix())
               for n, ids in enumerate(schedule(metadata), 1)]
    plan = dict(schema_version="authorized-final100-staged-v1", created_at=datetime.now(UTC).isoformat(),
                authorization="User explicitly approved starting progressive final testing after first5 then10 plan,2026-10-20.",
                batches=batches, selection_policy="Preassigned difficulty3:4:3 cycle, round-robin family, ascending variants; no outcome-based selection.",
                budget=BUDGET, dataset_manifest_sha256=sha(DATASET / "manifest.json"),
                source_sha256=sources(), product_checkpoint="12c0e9029459fe1a6904891feb23e5822a59b69f",
                no_tuning_on_final=True, stop_policy="Finish and score current bounded batch; no next batch after any nondelivery, final defect, input-audit flag, quota or connection issue.")
    validate_plan(plan, split, BUDGET["model"])
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(plan=str(PLAN), batches=len(batches), first5=batches[0]["ids"], total=100), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", required=True)
    parser.parse_args()
    create()
