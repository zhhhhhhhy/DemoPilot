"""Fresh Core generation with clarified goals and full-fixture business gates.

This is a targeted regression after independent audit, not a replacement for
the frozen sales-intent A/B score. No generated HTML/CSS/JS is edited by this
driver. All changes are performed by the real Core CLI loop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from demopilot.config import Settings
from demopilot.core_loop import CoreBuilderLoop
from demopilot.models import DemoRun, RunStatus, build_intent_statement
from demopilot.storage import RunStore
from run_codex_cli_eval_set import compact_result, load_cases
from run_sales_intent_paired_real import HiddenAnswerHarness, TracingProvider, core_request, digest, final_pass, write_json
from audit_sales_intent_paired_results import audit_one, frozen_protocol, sha256
from materialize_business_gates import ROOT, DEST, IDS


def prepared(case_id):
    _, sources = load_cases()
    source = sources[case_id]
    contract = json.loads((DEST / "testdata" / case_id / "acceptance.json").read_text(encoding="utf-8"))
    answer = json.loads((ROOT / "evaluation_sets/sales-intent-v1/sales-clarifications" / f"{case_id}.json").read_text(encoding="utf-8"))["answers"][0]["answer"]
    request = core_request({"source": source, "raw_sales_brief": contract["goal"] + " " + answer}, "intent-agent")
    request.evaluation_dataset = "sales-business-v2"
    request.evaluation_intent = contract["intent"]
    request.evaluation_goal = contract["goal"]
    request.evaluation_flow_steps = contract["flow_steps"]
    request.must_haves = source["must_haves"]
    request.acceptance_criteria = contract["expected_result"]
    request.evaluation_method = contract["evaluation_method"] + contract["expected_result"]
    return source, request


async def execute(args):
    settings = Settings()
    store = RunStore(settings.data_dir)
    provider = TracingProvider(command=settings.codex_command, model="gpt-6.1-sol", reasoning_effort="medium", timeout_seconds=300, cwd=ROOT)
    rows = []
    for case_id in IDS:
        result_path = args.output_dir / case_id / "result.json"
        source, request = prepared(case_id)
        if result_path.exists():
            rows.append(json.loads(result_path.read_text(encoding="utf-8")))
            continue
        progress_path = args.output_dir / case_id / "progress.json"
        if progress_path.exists():
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            run = store.get(progress["run_id"])
            if run is None or run.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                raise RuntimeError("Inspect nonterminal run before resuming; no duplicate CLI launched")
        else:
            run = DemoRun(id=uuid4().hex[:12], request=request)
            run.outputs["intent_statement"] = build_intent_statement(request)
            store.create(run)
            write_json(progress_path, {"run_id": run.id, "status": "core_running"})
            try:
                await CoreBuilderLoop(store, HiddenAnswerHarness(provider, case_id), project_root=ROOT, max_revision_rounds=2).execute(run)
            except BaseException as exc:
                run.status = RunStatus.CANCELLED if isinstance(exc, asyncio.CancelledError) else RunStatus.FAILED
                run.publication_status = "hidden"
                run.error = f"{type(exc).__name__}: {exc}"
                store.save(run)
                if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                    raise
        row = compact_result(source, run.model_dump(mode="json"))
        row.update(arm="coverage-repaired", final_pass=final_pass(row), run_dir=str(store.run_dir(run.id)))
        write_json(result_path, row)
        write_json(progress_path, {"run_id": run.id, "status": "terminal", "final_pass": row["final_pass"]})
        rows.append(row)
        write_json(args.output_dir / "results.json", {"results": rows, "real_runs": True, "not_an_ab_rerun": True})
        print(json.dumps({key: row[key] for key in ("case_id", "run_id", "final_pass", "revision_count")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8093")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    context_path = args.output_dir / "context.json"
    code_paths = [Path(__file__), ROOT / "scripts/materialize_business_gates.py", ROOT / "backend/src/demopilot/core_loop.py", ROOT / "backend/src/demopilot/models.py", ROOT / "scripts/audit_sales_intent_paired_results.py"]
    context = {"purpose": "Targeted regression after clarified business goals and expanded gates; not the original A/B", "cases": list(IDS), "model": "gpt-6.1-sol", "reasoning_effort": "medium", "timeout": 300, "revision_budget": 2,
               "code_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in code_paths},
               "fixture_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in (DEST / "testdata").glob("*/*.json")}}
    if args.freeze:
        if context_path.exists():
            raise SystemExit("Refusing to overwrite frozen context")
        for case_id in IDS:
            prepared(case_id)
        write_json(context_path, context)
        protocol = frozen_protocol()
        protocol.update(arms=["coverage-repaired"], experiment_type="targeted_business_regression")
        write_json(args.output_dir / "external-audit-protocol.json", protocol)
        print(json.dumps({"frozen_cases": len(IDS), "output": str(args.output_dir)}))
    elif not context_path.exists() or json.loads(context_path.read_text(encoding="utf-8")) != context:
        raise SystemExit("Freeze and preserve context before execution")
    elif args.real:
        asyncio.run(execute(args))
    elif args.audit_only:
        from playwright.sync_api import sync_playwright
        rows = json.loads((args.output_dir / "results.json").read_text(encoding="utf-8"))["results"]
        report = {"created_at": datetime.now(UTC).isoformat(), "rows": [], "feedback_to_builder": False, "not_an_ab_rerun": True}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for row in rows:
                    report["rows"].append(audit_one(browser, row, args.output_dir / "external-audit", args.base_url))
                    report["business_pass_count"] = sum(item["business_status"] == "passed" for item in report["rows"])
                    write_json(args.output_dir / "external-business-audit.json", report)
            finally:
                browser.close()
        print(json.dumps({"business_pass_count": report["business_pass_count"], "case_count": len(IDS)}))
    else:
        raise SystemExit("Choose --freeze, --real or --audit-only")


if __name__ == "__main__":
    main()
