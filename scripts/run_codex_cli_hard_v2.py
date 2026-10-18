"""Run the isolated hard-v2 Agent Core cases through real Codex CLI.

This runner is intentionally separate from the historical v1 runner and never
changes the v1 denominator. It reports terminal cases with the same release
gate fields plus an explicit evaluation_dataset marker.
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
CASES_PATH = ROOT / "evaluation_sets" / "codex-cli-v2-hard" / "cases.json"
TERMINAL = {"completed", "failed", "cancelled"}


def load_cases() -> dict[str, dict[str, Any]]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in payload["cases"]}
    if len(cases) != 8 or any(item["difficulty"] != "hard" for item in cases.values()):
        raise RuntimeError("hard-v2 cases.json must contain exactly 8 hard cases")
    return cases


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


def payload(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "client_name": "Codex CLI Agent Core Hard v2",
        "project_name": case["name"],
        "industry": case["industry"],
        "scenario": case["intent"],
        "audience": case["audience"],
        "must_haves": case["must_haves"],
        "boundaries": ["只交付本地静态演示", "不得连接外部服务", "使用 hard-v2 本地 testdata"],
        "priority": "先完成全流程，再保持分支、隔离和审计状态一致",
        "acceptance_criteria": case["acceptance_criteria"],
        "constraints": ["必须通过每条 authored browser journey", "失败保留证据并定向返工"],
        "brand_tone": "清晰、克制、可验证",
        "primary_color": "#0071e3",
        "provider": "codex_cli",
        "evaluation_mode": "core_generation",
        "evaluation_dataset": "codex-cli-v2-hard",
        "evaluation_case_id": case["id"],
        "evaluation_difficulty": "hard",
        "evaluation_intent": case["intent"],
        "evaluation_goal": case["goal"],
        "evaluation_flow_steps": case["flow_steps"],
        "evaluation_method": case["evaluation_method"],
        "evaluation_assets": [],
        "evaluation_asset_sha256": {},
        "evaluation_browser_contract": case["browser_contract"],
    }


def compact(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    outputs = run.get("outputs", {})
    acceptances = [
        (int(key.rsplit("_", 1)[-1]), value)
        for key, value in outputs.items()
        if key.startswith("core_acceptance_iteration_") and isinstance(value, dict)
    ]
    latest = max(acceptances, key=lambda item: item[0])[1] if acceptances else {}
    post = outputs.get("post_publish_audit", {})
    return {
        "case_id": case["id"],
        "evaluation_dataset": "codex-cli-v2-hard",
        "difficulty": "hard",
        "flow_count": len(case["flow_steps"]),
        "run_id": run.get("id"),
        "status": run.get("status"),
        "quality_gate": run.get("quality_gate"),
        "publication_status": run.get("publication_status"),
        "agent_calls": run.get("agent_calls", 0),
        "revision_count": run.get("revision_count", 0),
        "browser_status": latest.get("status", "not_run"),
        "browser_checks": latest.get("checks", []),
        "browser_issues": latest.get("issues", []),
        "post_publish_audit_status": post.get("status", "not_run"),
        "post_publish_fresh_browser_context": post.get("fresh_browser_context", False),
        "error": run.get("error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cases = load_cases()
    selected = list(cases.values())
    if args.case_id:
        unknown = [item for item in args.case_id if item not in cases]
        if unknown:
            raise SystemExit("Unknown case IDs: " + ", ".join(unknown))
        selected = [cases[item] for item in args.case_id]
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
            if args.dry_run:
                results.append({"case_id": case["id"], "evaluation_dataset": "codex-cli-v2-hard", "difficulty": "hard", "flow_count": len(case["flow_steps"]), "test_count": len(case["browser_contract"]["tests"]), "status": "dry_run"})
                continue
            if not args.real:
                raise SystemExit("Refusing to start a real run without --real")
            response = client.post(f"{base_url}/api/runs", json=payload(case))
            response.raise_for_status()
            finished = wait_for_run(client, base_url, response.json()["id"], args.timeout)
            results.append(compact(case, finished))
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    summary = {
        "schema_version": "codex-cli-hard-v2-result",
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "codex_cli",
        "evaluation_dataset": "codex-cli-v2-hard",
        "real_runs": bool(args.real and not args.dry_run),
        "case_count": len(results),
        "tier_counts": dict(Counter(item["difficulty"] for item in results)),
        "results": results,
    }
    output = args.output or ROOT / "evaluation_sets" / "codex-cli-v2-hard" / "results" / f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "case_count": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
