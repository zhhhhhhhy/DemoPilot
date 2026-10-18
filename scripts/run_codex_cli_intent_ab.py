"""Run a raw-sales versus confirmed-intent Core Builder pilot.

The two variants use the same prompt template and deterministic gates. Only
the structured intent fields and the intent-profile marker differ. This does
not claim to test an AI interviewer because the current product has no such
component; it measures the downstream value of the manually confirmed intent
package and preserves that boundary in the report.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from run_codex_cli_eval_set import compact_result, load_cases, resolve_assets, wait_for_run


ROOT = Path(__file__).resolve().parents[1]
SET_ROOT = ROOT / "evaluation_sets" / "sales-intent-v1"
VARIANTS = ("raw-sales", "intent-confirmed")


def load_intent_cases() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    payload = json.loads((SET_ROOT / "cases.json").read_text(encoding="utf-8"))
    gold = json.loads((SET_ROOT / "gold" / "intent-gold.json").read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in payload["cases"]}
    gold_by_id = {item["case_id"]: item for item in gold["cases"]}
    _, source_cases = load_cases()
    selected = []
    for case_id, item in cases.items():
        source = source_cases[item["source_case_id"]]
        selected.append({**item, "source": source, "gold": gold_by_id[case_id]})
    return selected, gold_by_id


def build_payload(item: dict[str, Any], variant: str) -> dict[str, Any]:
    source = item["source"]
    gold = item["gold"]
    assets, asset_sha256 = resolve_assets(source)
    structured = variant == "intent-confirmed"
    return {
        "client_name": "Codex CLI Sales Intent Evaluation",
        "project_name": source["name"],
        "industry": source["industry"],
        "scenario": item["raw_sales_brief"],
        "audience": gold["actor"] if structured else "销售人员",
        "must_haves": list(gold["must_haves"]) if structured else [],
        "boundaries": ["只交付本地静态演示"],
        "priority": "先完成可在浏览器中复核的核心销售演示",
        "acceptance_criteria": list(gold["acceptance"]) if structured else [],
        "constraints": list(gold["constraints"]),
        "intent_confirmed": True,
        "brand_tone": source.get("brand_tone", "清晰、克制、可验证"),
        "primary_color": source.get("primary_color", "#0071e3"),
        "provider": "codex_cli",
        "evaluation_mode": "core_generation",
        "evaluation_prompt_profile": "treatment-current",
        "evaluation_intent_profile": variant,
        "evaluation_case_id": source["id"],
        "evaluation_dataset": "codex-cli-v1",
        "evaluation_difficulty": source["difficulty"],
        "evaluation_intent": gold["problem"] if structured else None,
        "evaluation_goal": gold["desired_outcome"] if structured else None,
        "evaluation_flow_steps": list(gold["flow_steps"]) if structured else [],
        "evaluation_method": list(source["evaluation_method"]) if structured else [],
        "evaluation_assets": assets,
        "evaluation_asset_sha256": asset_sha256,
        "evaluation_browser_contract": source.get("browser_contract", {}),
    }


def metrics(results: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    published = [
        item
        for item in results
        if item.get("publication_status") == "published"
        and item.get("post_publish_audit_status") == "passed"
        and item.get("post_publish_fresh_browser_context") is True
    ]
    browser_pass = [item for item in results if item.get("browser_status") == "passed"]
    return {
        "variant": variant,
        "case_count": len(results),
        "published_rate": f"{len(published)}/{len(results)}" if results else "0/0",
        "business_contract_pass_rate": f"{len(browser_pass)}/{len(results)}" if results else "0/0",
        "revision_total": sum(int(item.get("revision_count", 0)) for item in results),
        "revision_average": round(sum(int(item.get("revision_count", 0)) for item in results) / len(results), 2) if results else 0,
        "agent_calls_total": sum(int(item.get("agent_calls", 0)) for item in results),
        "tier_counts": dict(Counter(item.get("difficulty") for item in results)),
        "intent_fidelity": "not_measured; current product has no AI extraction step",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.real and not args.dry_run:
        raise SystemExit("Refusing to start real runs without --real; use --dry-run for validation")
    selected, _ = load_intent_cases()
    if args.case_id:
        selected = [item for item in selected if item["id"] in set(args.case_id)]
    if not selected:
        raise SystemExit("No sales-intent cases selected")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    base_url = args.base_url.rstrip("/")
    created_at = datetime.now(UTC).isoformat()
    variants: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=30) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        if not health.json().get("providers", {}).get("codex_cli"):
            raise RuntimeError("DemoPilot backend does not report codex_cli=true")
        for variant in VARIANTS:
            results: list[dict[str, Any]] = []
            for item in selected:
                payload = build_payload(item, variant)
                if args.dry_run:
                    results.append({"case_id": item["id"], "intent_profile": variant, "scenario": payload["scenario"], "structured_fields": bool(payload["must_haves"])})
                    continue
                response = client.post(f"{base_url}/api/runs", json=payload)
                response.raise_for_status()
                finished = wait_for_run(client, base_url, response.json()["id"], args.timeout)
                result = compact_result(item["source"], finished)
                result["intent_profile"] = variant
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            summary = {
                "schema_version": "sales-intent-pilot-variant",
                "created_at": created_at,
                "provider": "codex_cli",
                "intent_profile": variant,
                "real_runs": bool(args.real and not args.dry_run),
                "case_ids": [item["id"] for item in selected],
                "metrics": metrics(results, variant) if args.real and not args.dry_run else {"case_count": len(results)},
                "results": results,
            }
            path = args.output_dir / f"intent-ab-{variant}.json"
            path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            variants[variant] = summary
    paired = {
        item["id"]: {variant: next(result for result in variants[variant]["results"] if result["case_id"] == item["id"]) for variant in VARIANTS}
        for item in selected
    }
    report = {
        "schema_version": "sales-intent-pilot",
        "created_at": created_at,
        "provider": "codex_cli",
        "real_runs": bool(args.real and not args.dry_run),
        "cases": [item["id"] for item in selected],
        "variants": variants,
        "paired": paired,
        "interpretation": "This pilot measures downstream release behavior of raw versus manually confirmed structured intent. It does not measure AI intent extraction accuracy because the current product has no AI intent-acquisition step.",
        "causal_claim": "not_estimated; small sequential pilot",
    }
    report_path = args.output_dir / "intent-ab-pilot.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(report_path), "case_count": len(selected), "variants": list(VARIANTS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
