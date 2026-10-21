"""Development-qualified, same-budget fresh replay of the observed15 only."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from sales_final_campaign import BUDGET, DATASET, ROOT, read, sha, sources
from sales_observed_rerun import original_records, validate_selection

PLAN = ROOT / "docs/sales-benchmark-v3/cli-runtime-repair-20261021/PLAN.json"
OUTPUT = ROOT / ".data/sales-benchmark-v3/runtime-repair15-20261021-v1"
PREVIOUS = ROOT / ".data/sales-benchmark-v3/observed15-rerun-20261021-v1"


def development_ids():
    pilot=set(read(DATASET/"pilot-20.json")["case_ids"])
    opened=[c for c in read(DATASET/"cases.json")["cases"] if c["split"]=="development" and c["id"] in pilot]
    # Capability strata, not the IDs/answers of the failed final cases.
    pairs=[("rate_override","manual_override"),("validity_dates","expiry")]
    return [min(c["id"] for c in opened if (c["expected_plan"]["pricing_rule"]["kind"],c["expected_plan"]["workflow"])==pair) for pair in pairs]


def qualified_development(path, model):
    from run_sales_benchmark_pilot import code_manifest
    path=Path(path).resolve()
    result, context=read(path),read(path.parent/"context.json")
    rows=result.get("rows",[])
    if (context["pilot_ids"]!=development_ids() or context["execution_split"]!="development"
            or context["code_sha256"]!=code_manifest() or context["dataset_manifest_sha256"]!=sha(DATASET/"manifest.json")
            or any(context.get(k)!=v for k,v in BUDGET.items()) or model!=BUDGET["model"]
            or len(rows)!=2 or {r["case_id"] for r in rows}!=set(development_ids())
            or any(not r["delivery_pass"] or not r["final_functional_pass"] or not r["confirmation_semantics_match"]
                   or set(r.get("exact_served_assets",[]))!={"index.html","app.js","styles.css"} for r in rows)):
        raise ValueError("Require both fixed capability-selected development tasks passed on the same source/model/budgets")
    controls=read(path.parent/"runtime-control.json")
    events=[json.loads(line) for line in (path.parent/"sales-core/runtime-events.jsonl").read_text("utf-8").splitlines()]
    states=[e["state"] for e in events]
    if not controls.get("injected_host_gap") or not all(state in states for state in ("paused","checking","half_open","ready")):
        raise ValueError("Development must demonstrate resume-check and real-CLI half-open completion")
    return dict(results=path.relative_to(ROOT).as_posix(),results_sha256=sha(path),
                context_sha256=sha(path.parent/"context.json"),control_sha256=sha(path.parent/"runtime-control.json"),
                runtime_events_sha256=sha(path.parent/"sales-core/runtime-events.jsonl"),ids=development_ids())


def verify(plan):
    original,records=original_records()
    validate_selection(plan,original,read(DATASET/"split.json"),plan["budget"]["model"])
    if records!=plan["original_batches"] or sources()!=plan["source_sha256"]:
        raise ValueError("Frozen source or original13/15 changed")
    if sha(DATASET/"manifest.json")!=plan["dataset_manifest_sha256"]:
        raise ValueError("Frozen dataset changed")
    for relative,digest in plan["previous7_records"].items():
        if sha(ROOT/relative)!=digest:
            raise ValueError("Preserve original7/15 evidence")
    if qualified_development(ROOT/plan["development"]["results"],plan["budget"]["model"])!=plan["development"]:
        raise ValueError("Development qualification evidence changed")
    if any(sha(ROOT/p)!=h for p,h in read(DATASET/"manifest.json")["files"].items()):
        raise ValueError("Original inputs/acceptance changed")
    if any((ROOT/b["output"]).exists() for b in original["batches"][2:]):
        raise ValueError("Remaining85 must stay unstarted")


def unlock(plan_path,model,output):
    if not plan_path or Path(plan_path).resolve()!=PLAN.resolve():
        raise ValueError("Runtime repair15 requires its explicit separate authorization plan")
    plan=read(PLAN)
    if model!=BUDGET["model"] or Path(output).resolve()!=OUTPUT.resolve():
        raise ValueError("Use the same model and separate fresh output")
    if (Path(output)/"context.json").exists():
        raise ValueError("Never overwrite/relaunch a started replay")
    verify(plan)
    return plan["ids"],dict(plan=PLAN.relative_to(ROOT).as_posix(),plan_sha256=sha(PLAN),
                           original_scores=["13/15","7/15"],remaining_unexecuted=85,
                           boundary="Previously observed15 regression; no new unseen data, no score stitching.")


def create(development):
    if PLAN.exists() or OUTPUT.exists():
        raise FileExistsError("Preserve existing plan and runs")
    original,records=original_records()
    old=read(PREVIOUS/"results.json")
    if old["summary"]["delivered"]!=7:
        raise ValueError("Preserve the complete7/15 run")
    plan=dict(schema_version="observed-final15-regression-v1",initiative="runtime-repair15-v1",created_at=datetime.now(UTC).isoformat(),
              authorization="User explicitly requests generic CLI/runtime repair, development qualification, then complete same-condition original15 replay; preserve13/15and7/15,85untouched,2026-10-21.",
              ids=[i for b in original["batches"][:2] for i in b["ids"]],original_delivered=13,remaining_unexecuted=85,
              original_batches=records,budget=dict(BUDGET),dataset_manifest_sha256=sha(DATASET/"manifest.json"),
              source_sha256=sources(),development=qualified_development(development,BUDGET["model"]),
              previous7_records={(PREVIOUS/name).relative_to(ROOT).as_posix():sha(PREVIOUS/name) for name in ("results.json","context.json")},
              output=OUTPUT.relative_to(ROOT).as_posix(),
              stop_policy="Shared transport circuit pauses new calls. Explicit zero-token connection check may release queued original-budget work; never replay writes, reset budgets, edit source/data/criteria or unlock85. Retain all failed/unstarted outcomes.",
              change_boundary="Runtime supervision, child proxy/config isolation and Core within-budget finish guidance only. Business rules and browser criteria unchanged.")
    verify(plan)
    PLAN.parent.mkdir(parents=True,exist_ok=True)
    PLAN.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps(dict(plan=PLAN.relative_to(ROOT).as_posix(),ids=plan["ids"],development=plan["development"])))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development",type=Path,required=True)
    args=parser.parse_args()
    create(args.development)
