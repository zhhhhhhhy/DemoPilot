"""Append a no-interview, full-business-information arm to frozen quotation A/B.

Reuse the original Core loop and browser scorer byte-for-byte. This is a later
control arm, not a new contemporaneous randomized three-arm experiment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import run_quotation_intent_ab as base
from demopilot.models import DemoRequest, DemoRun, RunStatus, build_intent_statement

ROOT, DATASET = base.ROOT, base.DATASET
ARM = "full-rules"
EXTRA_CODE = ["scripts/run_quotation_full_rules.py", "scripts/report_quotation_three_arms.py"]
OLD_HELD = DATASET / "results/heldout-20261016"
OLD_DEV = DATASET / "results/development-v2-20261016"


def supplied_facts(case):
    script = base.load_json(DATASET / case["seller_script"])
    return [answer["text"] for answer in script["answers"]]


def make_full_rules_request(case):
    # Change only the actual business information, leaving every engineering
    # field identical to the original direct arm. No typed-intent generation.
    payload = base.make_request(case, "direct").model_dump(mode="json")
    payload["evaluation_intent"] += "\n销售已回答：" + "\n".join(supplied_facts(case))
    return DemoRequest.model_validate(payload)


def freeze_context():
    original = base.load_json(OLD_HELD / "context.json")
    changed = [path for path, digest in original["code_sha256"].items() if base.sha(ROOT / path) != digest]
    if changed:
        raise RuntimeError(f"Original Core/scorer changed: {changed}")
    for path, digest in base.load_json(DATASET / "manifest.json")["files"].items():
        if base.sha(ROOT / path) != digest:
            raise RuntimeError(f"Original data changed: {path}")
    if base.sha(DATASET / "manifest.json") != original["data_manifest_sha256"]:
        raise RuntimeError("Original manifest changed")
    if base.sha(DATASET / "sources.json") != original["source_registry_sha256"]:
        raise RuntimeError("Original source registry changed")
    cases = base.all_cases()
    historical = {}
    for directory in (OLD_DEV, OLD_HELD):
        for filename in ("context.json", "results.json", "business-audit.json"):
            path = directory / filename
            historical[str(path.relative_to(ROOT))] = base.sha(path)
    context = dict(original)
    context.update(
        schema_version="quotation-full-rules-control-v1", split="all",
        case_ids=[case["id"] for case in cases], arms=[ARM], max_parallel_cases=2,
        extension_code_sha256={path: base.sha(ROOT / path) for path in EXTRA_CODE},
        historical_sha256=historical,
        input_requests={case["id"]: make_full_rules_request(case).model_dump(mode="json") for case in cases},
        input_rule="Same raw brief plus every verbatim seller answer, in authored order. No interview, typed intent, copied B output, hidden vectors or expected numbers.",
        permitted_difference_from_direct=["evaluation_intent"],
        core_budget="Original gpt-6.1-sol / medium / 300 seconds per CLI call / at most2 repair rounds. Intent calls zero; B overhead remains separately counted.",
        comparison="Later appended C arm compared with original A/B outcomes. Four development cases remain separate from six primary cases. No original rescore.",
        limitation="The original outputs were already known before C was designed; this is retrospective exploratory ablation, not fresh blind or contemporaneous randomized testing. Remote model-service internals and timing drift are unobserved.",
    )
    context.pop("arm_order", None)
    return context, cases


async def run_case(case, output_dir, context):
    target = output_dir / case["id"] / ARM
    target.mkdir(parents=True, exist_ok=True)
    result_path, progress_path = target / "result.json", target / "progress.json"
    if result_path.exists():
        return base.load_json(result_path)
    store = base.RunStore(output_dir / "runtime")
    if progress_path.exists():
        progress = base.load_json(progress_path)
        run = store.get(progress["run_id"])
        if run is None or run.status not in base.TERMINAL:
            raise RuntimeError("Inspect interrupted nonterminal run; duplicate Core launch prohibited")
        started = progress["started_at"]
        elapsed = max(0, (run.updated_at - datetime.fromisoformat(started)).total_seconds())
    else:
        started, clock_start = datetime.now(UTC).isoformat(), time.monotonic()
        request = make_full_rules_request(case)
        base.write_json(target / "request.json", request.model_dump(mode="json"))
        base.write_json(target / "supplied-facts.json", dict(facts=supplied_facts(case), source=case["seller_script"], intent_calls=0))
        run = DemoRun(id=uuid4().hex[:12], request=request)
        store.create(run)
        progress = dict(run_id=run.id, started_at=started, status="core_running", intent_calls=0)
        base.write_json(progress_path, progress)
        try:
            run.outputs["intent_statement"] = build_intent_statement(run.request)
            store.save(run)
            settings = base.Settings()
            provider = base.TracingProvider(command=settings.codex_command, model=context["model"],
                                            reasoning_effort=context["reasoning_effort"],
                                            timeout_seconds=context["cli_timeout_seconds"], cwd=ROOT)
            await base.QuotationLoop(store, base.CodexCliHarness(provider), project_root=ROOT,
                                     max_revision_rounds=context["max_revision_rounds"]).execute(run)
        except BaseException as exc:
            run.status = RunStatus.CANCELLED if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else RunStatus.FAILED
            run.publication_status, run.quality_gate = "hidden", "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:800]
            store.save(run)
            base.write_json(target / "execution-error.json", dict(type=type(exc).__name__, message=str(exc)))
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                raise
        elapsed = time.monotonic() - clock_start
    row = base.compact_result(base.source_meta(case), run.model_dump(mode="json"))
    row.update(arm=ARM, split=case["split"], elapsed_seconds=round(elapsed, 3), intent_cli_calls=0,
               total_cli_calls=run.agent_calls, started_at=started, finished_at=datetime.now(UTC).isoformat(),
               run_dir=str(store.run_dir(run.id)), business_status="not_run")
    base.write_json(result_path, row)
    base.write_json(target / "run-metrics.json", base.run_metrics(run, store.run_dir(run.id)))
    progress.update(status="terminal", terminal_status=run.status.value)
    base.write_json(progress_path, progress)
    return row


async def execute(output_dir, context, cases):
    results, slots, lock = [], asyncio.Semaphore(2), asyncio.Lock()

    async def one(case):
        async with slots:
            current, _ = freeze_context()
            if current != context:
                raise RuntimeError("Frozen extension context changed")
            row = await run_case(case, output_dir, context)
            async with lock:
                results.append(row)
                base.write_json(output_dir / "results.json", dict(real_cli=True, split="all", planned_case_count=10,
                    planned_arm_count=10, results=results, business_scoring="Independent frozen audit after all terminal results; no feedback or score replacement"))
            print(json.dumps({key: row.get(key) for key in ("case_id", "arm", "run_id", "status", "publication_status", "revision_count", "total_cli_calls", "elapsed_seconds")}), flush=True)

    await asyncio.gather(*(one(case) for case in cases))


def audit(output_dir, context):
    from audit_quotation_intent import audit_row
    from playwright.sync_api import sync_playwright
    results = base.load_json(output_dir / "results.json")
    rows = results["results"]
    if len(rows) != 10 or len({r["case_id"] for r in rows}) != 10:
        raise RuntimeError("All ten new arms must be terminal before scoring")
    path = output_dir / "business-audit.json"
    if path.exists():
        raise RuntimeError("Refusing to overwrite original independent scoring")
    audits = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for row in rows:
                audits.append(audit_row(browser, row, output_dir / "business-audit"))
                base.write_json(output_dir / "business-audit-progress.json", dict(rows=audits, feedback_to_builder=False))
        finally:
            browser.close()
    base.write_json(path, dict(created_at=datetime.now(UTC).isoformat(), split="all", arm=ARM,
        rows=audits, feedback_to_builder=False, full_planned_denominator=True,
        provenance="Unmodified audit_row from original frozen scorer; no original A/B rescoring"))
    print(json.dumps(dict(cases=len(audits), business_pass=sum(r["end_to_end_pass"] for r in audits),
        planned_journeys=sum(r["planned_journeys"] for r in audits), passed_journeys=sum(r.get("passed_journeys",0) for r in audits))), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("freeze", "real", "audit"):
        mode.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    context, cases = freeze_context()
    context_path = args.output_dir / "context.json"
    if args.freeze:
        if context_path.exists():
            raise RuntimeError("Refusing to replace frozen context")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        base.write_json(context_path, context)
        base.write_json(args.output_dir / "freeze-record.json", dict(created_at=datetime.now(UTC).isoformat(),
            real_runs=False, context_sha256=base.sha(context_path), planned_cases=10, primary_cases=6))
        for relative in [*base.FROZEN_CODE, *EXTRA_CODE]:
            target = args.output_dir / "frozen-code" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        for relative in base.load_json(DATASET / "manifest.json")["files"]:
            target = args.output_dir / "frozen-data" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        print(json.dumps(dict(frozen=True, cases=10, primary_cases=6, intent_calls=0)))
    else:
        if not context_path.exists() or base.load_json(context_path) != context:
            raise RuntimeError("Freeze exact input and code before execution")
        if args.real:
            asyncio.run(execute(args.output_dir, context, cases))
        else:
            audit(args.output_dir, context)


if __name__ == "__main__":
    main()
