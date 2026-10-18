"""One development-only integration regression; never a replacement A/B score."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from run_quotation_intent_ab import all_cases, freeze_context, run_arm, write_json
from run_sales_intent_agent_pilot import intent_gate_errors
from audit_quotation_intent import audit_row

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prior = ROOT / "evaluation_sets/quotation-intent-v1/results/development-v2-20261016/quotation-01/clarify/intent/turn-02-output.json"
    output = json.loads(prior.read_text(encoding="utf-8"))
    assert output["status"] == "ready" and output["flow_steps"] == [] and output["questions"] == []
    errors = intent_gate_errors(output, "quotation-01")
    assert errors == [], errors
    write_json(args.output_dir / "recorded-intent-replay.json", dict(
        prior_source=str(prior), previous_errors=["flow_steps must not be empty"],
        current_errors=errors, expected_business_rules_unchanged=True,
        interpretation="Replay of the actually rejected ready intent, not a fabricated model success."))
    runtime, _ = freeze_context(SimpleNamespace(split="development", model="gpt-6.1-sol", cli_timeout=300))
    runtime["experiment_type"] = "single_development_regression_not_ab"
    context_path = args.output_dir / "context.json"
    if context_path.exists() and json.loads(context_path.read_text(encoding="utf-8")) != runtime:
        raise RuntimeError("Regression context changed; preserve existing run")
    write_json(context_path, runtime)
    case = next(case for case in all_cases() if case["id"] == "quotation-01")
    row = asyncio.run(run_arm(case, "clarify", args.output_dir, runtime))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            audit = audit_row(browser, row, args.output_dir / "business-audit")
        finally:
            browser.close()
    write_json(args.output_dir / "regression-audit.json", audit)
    print(json.dumps(dict(case_id=case["id"], arm="clarify", run_id=row["run_id"],
                          published=row["publication_status"], business_pass=audit["end_to_end_pass"],
                          passed_journeys=audit.get("passed_journeys", 0),
                          planned_journeys=audit["planned_journeys"],
                          not_an_ab_replacement=True), ensure_ascii=False))


if __name__ == "__main__":
    main()
