"""Run the isolated 20-case Agent Core set through the real Codex CLI provider.

The script deliberately talks to DemoPilot's normal /api/runs endpoint. It
does not call the Mock provider and it never sends invoice-gold.json to the
model. A full run is sequential because each case can consume a long-lived
Codex CLI session and the local provider serializes CLI processes.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
SET_ROOT = ROOT / "evaluation_sets" / "codex-cli-v1"
CASES_PATH = SET_ROOT / "cases.json"
MANIFEST_PATH = SET_ROOT / "invoice-manifest.json"
TERMINAL = {"completed", "failed", "cancelled"}


def load_cases() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in payload["cases"]}
    if len(cases) != 20:
        raise RuntimeError(f"Expected 20 unique cases, found {len(cases)}")
    counts = Counter(item["difficulty"] for item in cases.values())
    if counts != Counter(simple=10, medium=5, hard=5):
        raise RuntimeError(f"Unexpected tier counts: {counts}")
    return payload, cases


def resolve_assets(case: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    if not case.get("assets"):
        return [], {}
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in manifest["fixtures"]}
    paths: list[str] = []
    checksums: dict[str, str] = {}
    for asset_id in case["assets"]:
        item = by_id.get(asset_id)
        if not item:
            raise RuntimeError(f"Unknown evaluation asset: {asset_id}")
        path = (ROOT / item["local_path"]).resolve()
        if not path.is_file():
            raise RuntimeError(f"Missing evaluation asset: {path}")
        path_string = str(path)
        paths.append(path_string)
        checksums[path_string] = item["sha256"]
    return paths, checksums


def request_payload(
    set_payload: dict[str, Any], case: dict[str, Any], *, require_approval: bool
) -> dict[str, Any]:
    assets, asset_sha256 = resolve_assets(case)
    return {
        "client_name": "Codex CLI Agent Core Evaluation",
        "project_name": case["name"],
        "industry": case["industry"],
        "scenario": case["scenario"],
        "audience": case["audience"],
        "must_haves": case["must_haves"],
        "boundaries": set_payload["default_boundaries"],
        "priority": "先完成该用例的核心流程并让每一步可被浏览器复核",
        "acceptance_criteria": case["acceptance_criteria"],
        "constraints": set_payload["default_constraints"],
        "brand_tone": "清晰、克制、可验证",
        "primary_color": "#0071e3",
        "provider": "codex_cli",
        "evaluation_mode": "core_generation",
        "require_execution_approval": require_approval,
        "evaluation_case_id": case["id"],
        "evaluation_difficulty": case["difficulty"],
        "evaluation_intent": case["intent"],
        "evaluation_goal": case["goal"],
        "evaluation_flow_steps": case["flow_steps"],
        "evaluation_method": case["evaluation_method"],
        "evaluation_assets": assets,
        "evaluation_asset_sha256": asset_sha256,
        "evaluation_browser_contract": case.get("browser_contract", {}),
    }


def wait_for_run(client: httpx.Client, base_url: str, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"{base_url}/api/runs/{run_id}")
        response.raise_for_status()
        latest = response.json()
        if latest.get("status") in TERMINAL:
            return latest
        time.sleep(2)
    raise TimeoutError(f"run {run_id} did not finish; last status={latest.get('status')}")


def compact_result(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    outputs = run.get("outputs", {})
    validation = outputs.get("artifact_validation", {})
    browser = validation.get("browser_e2e", {}) if isinstance(validation, dict) else {}
    # A later failed revision can overwrite the final artifact summary after an
    # earlier revision already exercised Chromium. Preserve the strongest
    # observed browser evidence in the case result instead of reporting only
    # the last checkpoint.
    validation_candidates = [
        value
        for key, value in outputs.items()
        if key.startswith("artifact_validation_iteration_") and isinstance(value, dict)
    ]
    for candidate in validation_candidates:
        candidate_browser = candidate.get("browser_e2e", {})
        if isinstance(candidate_browser, dict) and candidate_browser.get("status") in {
            "passed",
            "failed",
            "unavailable",
        }:
            validation = candidate
            browser = candidate_browser
    reviewer = outputs.get("reviewer", {})
    if not isinstance(reviewer, dict):
        reviewer = {}
    return {
        "case_id": case["id"],
        "name": case["name"],
        "difficulty": case["difficulty"],
        "flow_count": len(case["flow_steps"]),
        "run_id": run.get("id"),
        "status": run.get("status"),
        "quality_gate": run.get("quality_gate"),
        "agent_calls": run.get("agent_calls", 0),
        "revision_count": run.get("revision_count", 0),
        "artifact_status": validation.get("status", "not_run"),
        "browser_status": browser.get("status", "not_run"),
        "browser_checks": browser.get("checks", []),
        "browser_issues": browser.get("issues", []),
        "reviewer_decision": reviewer.get("decision"),
        "reviewer_score": reviewer.get("overall_score"),
        "artifact_count": len(run.get("artifacts", [])),
        "error": run.get("error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--case-id", action="append", help="Run only this case; repeatable")
    parser.add_argument("--tier", choices=("simple", "medium", "hard"), action="append")
    parser.add_argument("--limit", type=int, help="Run at most this many selected cases")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print prompts without starting Codex")
    parser.add_argument("--real", action="store_true", help="Required to start real Codex CLI runs")
    parser.add_argument("--require-approval", action="store_true")
    args = parser.parse_args()
    set_payload, cases = load_cases()
    selected = list(cases.values())
    if args.case_id:
        unknown = [item for item in args.case_id if item not in cases]
        if unknown:
            raise SystemExit("Unknown case IDs: " + ", ".join(unknown))
        selected = [cases[item] for item in args.case_id]
    if args.tier:
        selected = [item for item in selected if item["difficulty"] in set(args.tier)]
    if args.limit is not None:
        selected = selected[: max(0, args.limit)]
    if not selected:
        raise SystemExit("No cases selected")

    base_url = args.base_url.rstrip("/")
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=30) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        if not health.json().get("providers", {}).get("codex_cli"):
            raise RuntimeError("DemoPilot backend does not report codex_cli=true")
        for case in selected:
            payload = request_payload(set_payload, case, require_approval=args.require_approval)
            if args.dry_run:
                results.append(
                    {
                        "case_id": case["id"],
                        "difficulty": case["difficulty"],
                        "flow_count": len(case["flow_steps"]),
                        "provider": payload["provider"],
                        "evaluation_fields_present": all(
                            payload[key]
                            for key in (
                                "evaluation_intent",
                                "evaluation_goal",
                                "evaluation_flow_steps",
                                "evaluation_method",
                            )
                        ),
                        "asset_count": len(payload["evaluation_assets"]),
                    }
                )
                continue
            if not args.real:
                raise SystemExit("Refusing to start a real run without --real; use --dry-run for validation")
            response = client.post(f"{base_url}/api/runs", json=payload)
            response.raise_for_status()
            created = response.json()
            finished = wait_for_run(client, base_url, created["id"], args.timeout)
            results.append(compact_result(case, finished))
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    summary = {
        "schema_version": "codex-cli-v1-result",
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "codex_cli",
        "real_runs": bool(args.real and not args.dry_run),
        "case_count": len(results),
        "tier_counts": dict(Counter(item["difficulty"] for item in results)),
        "results": results,
    }
    output = args.output or SET_ROOT / "results" / f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "case_count": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
