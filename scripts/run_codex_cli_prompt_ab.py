"""Run paired Core Builder Prompt variants on the same v1 cases.

Only ``evaluation_prompt_profile`` changes between variants. The API, testdata,
acceptance child, Chromium gates and publication rule remain the same.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from run_codex_cli_eval_set import (
    compact_result,
    load_cases,
    request_payload,
    wait_for_run,
)

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "evaluation_sets" / "codex-cli-ab-v1" / "experiment.json"
VARIANTS = ("control-legacy", "treatment-current")


def terminal_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    published = [
        item
        for item in results
        if item.get("publication_status") == "published"
        and item.get("post_publish_audit_status") == "passed"
        and item.get("post_publish_fresh_browser_context") is True
    ]
    return {
        "case_count": len(results),
        "published_count": len(published),
        "published_rate": f"{len(published)}/{len(results)}" if results else "0/0",
        "terminal_builder_failures": sum(
            1
            for item in results
            if item.get("status") in {"failed", "cancelled"}
            and item.get("publication_status") != "published"
        ),
        "revision_count_total": sum(int(item.get("revision_count", 0)) for item in results),
        "revision_count_median_input": sorted(int(item.get("revision_count", 0)) for item in results),
        "tier_counts": dict(Counter(item.get("difficulty") for item in results)),
    }


def load_selection(cases: dict[str, dict[str, Any]], selected: list[str] | None) -> list[dict[str, Any]]:
    if selected:
        unknown = [case_id for case_id in selected if case_id not in cases]
        if unknown:
            raise SystemExit("Unknown case IDs: " + ", ".join(unknown))
        return [cases[case_id] for case_id in selected]
    experiment = json.loads(EXPERIMENT.read_text(encoding="utf-8"))
    pilot_ids = experiment.get("pilot_selection", [])
    if not pilot_ids:
        raise SystemExit("experiment.json has no pilot_selection; pass --case-id explicitly")
    return load_selection(cases, pilot_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--case-id", action="append", help="Paired case; repeatable")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--real", action="store_true", help="Required to start real Codex CLI runs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-approval", action="store_true")
    args = parser.parse_args()
    if not args.real and not args.dry_run:
        raise SystemExit("Refusing to start real runs without --real; use --dry-run for validation")

    _, cases = load_cases()
    selected = load_selection(cases, args.case_id)
    base_url = args.base_url.rstrip("/")
    output_dir = args.output_dir or ROOT / "evaluation_sets" / "codex-cli-ab-v1" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).isoformat()
    variants: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=30) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        if not health.json().get("providers", {}).get("codex_cli"):
            raise RuntimeError("DemoPilot backend does not report codex_cli=true")
        schema = client.get(f"{base_url}/openapi.json")
        schema.raise_for_status()
        profile_schema = (
            schema.json().get("components", {}).get("schemas", {}).get("DemoRequest", {}).get("properties", {}).get("evaluation_prompt_profile", {})
        )
        if set(profile_schema.get("enum", [])) != set(VARIANTS):
            raise RuntimeError("API schema does not expose both prompt profiles; restart the API before running A/B")
        for profile in VARIANTS:
            results: list[dict[str, Any]] = []
            for case in selected:
                payload = request_payload(
                    {"default_boundaries": ["只交付本地静态演示"], "default_constraints": ["不得连接外部服务"]},
                    case,
                    require_approval=args.require_approval,
                    prompt_profile=profile,
                )
                if args.dry_run:
                    results.append(
                        {
                            "case_id": case["id"],
                            "difficulty": case["difficulty"],
                            "prompt_profile": profile,
                            "evaluation_fields_present": bool(payload.get("evaluation_intent")),
                        }
                    )
                    continue
                response = client.post(f"{base_url}/api/runs", json=payload)
                response.raise_for_status()
                run_id = response.json()["id"]
                finished = wait_for_run(client, base_url, run_id, args.timeout)
                result = compact_result(case, finished)
                result["prompt_profile"] = profile
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)

            summary = {
                "schema_version": "codex-cli-prompt-ab-variant-result",
                "created_at": created_at,
                "provider": "codex_cli",
                "prompt_profile": profile,
                "real_runs": bool(args.real and not args.dry_run),
                "case_ids": [case["id"] for case in selected],
                "case_count": len(results),
                "metrics": terminal_metrics(results) if args.real and not args.dry_run else {"case_count": len(results)},
                "results": results,
            }
            output = output_dir / f"prompt-ab-{profile}-20261008.json"
            output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            variants[profile] = summary

    paired = {
        case_id: {
            profile: next(item for item in variants[profile]["results"] if item["case_id"] == case_id)
            for profile in VARIANTS
        }
        for case_id in [case["id"] for case in selected]
    }
    report = {
        "schema_version": "codex-cli-prompt-ab-pilot",
        "created_at": created_at,
        "provider": "codex_cli",
        "real_runs": bool(args.real and not args.dry_run),
        "case_ids": [case["id"] for case in selected],
        "variants": variants,
        "paired": paired,
        "causal_claim": "not_estimated; pilot only" if args.real else "not_run",
    }
    report_path = output_dir / "prompt-ab-pilot-20261008.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(report_path), "case_count": len(selected), "variants": list(VARIANTS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
