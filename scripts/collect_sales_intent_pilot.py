"""Collect terminal sales-intent pilot runs after a runner-side timeout."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from run_codex_cli_intent_ab import VARIANTS, load_intent_cases, metrics
from run_codex_cli_eval_set import compact_result


RUN_IDS = {
    "raw-sales": {
        "simple-quote-generator-01": "41348131135f",
        "medium-lead-followup-01": "3c3d083ecbde",
        "hard-procurement-approval-01": "1bbbde25729c",
    },
    "intent-confirmed": {
        "simple-quote-generator-01": "6009812d5326",
        "medium-lead-followup-01": "e46fb4cc8e3b",
        "hard-procurement-approval-01": "c53d40dccd54",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    selected, _ = load_intent_cases()
    by_id = {item["id"]: item for item in selected}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    variants: dict[str, dict] = {}
    with httpx.Client(timeout=60) as client:
        for variant in VARIANTS:
            results = []
            for case_id, run_id in RUN_IDS[variant].items():
                run = client.get(f"{args.base_url.rstrip('/')}/api/runs/{run_id}").json()
                if run.get("status") not in {"completed", "failed", "cancelled"}:
                    raise RuntimeError(f"Run {run_id} is not terminal: {run.get('status')}")
                result = compact_result(by_id[case_id]["source"], run)
                result["intent_profile"] = variant
                results.append(result)
            summary = {
                "schema_version": "sales-intent-pilot-variant",
                "created_at": datetime.now(UTC).isoformat(),
                "provider": "codex_cli",
                "intent_profile": variant,
                "real_runs": True,
                "case_ids": list(RUN_IDS[variant]),
                "metrics": metrics(results, variant),
                "results": results,
            }
            (args.output_dir / f"intent-ab-{variant}.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            variants[variant] = summary
    paired = {
        case_id: {variant: next(item for item in variants[variant]["results"] if item["case_id"] == case_id) for variant in VARIANTS}
        for case_id in RUN_IDS["raw-sales"]
    }
    report = {
        "schema_version": "sales-intent-pilot",
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "codex_cli",
        "real_runs": True,
        "cases": list(RUN_IDS["raw-sales"]),
        "variants": variants,
        "paired": paired,
        "interpretation": "Downstream release pilot only: raw sales brief versus manually confirmed structured intent. The current product has no AI intent extraction step, so intent fidelity is not measured.",
        "collector_note": "The original runner hit its 1800-second wait while the final backend run was still active; this report was reconstructed read-only from the six terminal run IDs.",
        "causal_claim": "not_estimated; small sequential pilot",
    }
    output = args.output_dir / "intent-ab-pilot.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "case_count": len(paired)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
