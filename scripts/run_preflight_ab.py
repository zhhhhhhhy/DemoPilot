from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

CASES = ["retail-01", "logistics-01", "procurement-01"]
TERMINAL = {"completed", "failed", "cancelled"}


def wait_for(client: httpx.Client, base_url: str, evaluation_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"{base_url}/api/evaluations/{evaluation_id}")
        response.raise_for_status()
        last = response.json()
        if last.get("status") in TERMINAL:
            return last
        time.sleep(2)
    raise TimeoutError(f"evaluation {evaluation_id} did not finish; last={last}")


def create(
    client: httpx.Client,
    base_url: str,
    *,
    label: str,
    preflight_enabled: bool,
    baseline_id: str | None,
) -> dict[str, Any]:
    response = client.post(
        f"{base_url}/api/evaluations",
        json={
            "provider": "deepseek",
            "case_ids": CASES,
            "case_limit": len(CASES),
            "concurrency": 1,
            "version_label": label,
            "baseline_id": baseline_id,
            "skill_profile": "approved",
            "first_pass_only": False,
            "builder_preflight_enabled": preflight_enabled,
            "thresholds": {
                "min_success_rate": 0,
                "min_average_score": 0,
                "min_browser_pass_rate": 0,
                "min_feature_coverage_rate": 0,
                "max_average_agent_calls": 18,
            },
        },
    )
    response.raise_for_status()
    return response.json()


def run_detail(client: httpx.Client, base_url: str, run_id: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/api/runs/{run_id}")
    response.raise_for_status()
    run = response.json()
    outputs = run.get("outputs", {})
    preflights = [
        value
        for key, value in outputs.items()
        if key.startswith("builder_preflight_iteration_") and isinstance(value, dict)
    ]
    skill_calls = outputs.get("skill_trace", {}).get("calls", [])
    return {
        "run_id": run_id,
        "status": run.get("status"),
        "agent_calls": run.get("agent_calls"),
        "revisions": run.get("revision_count"),
        "preflight_blocks": sum(item.get("status") == "failed" for item in preflights),
        "preflight_statuses": [item.get("status") for item in preflights],
        "reviewer_final_calls": sum(
            item.get("stage") == "reviewer:final" for item in skill_calls if isinstance(item, dict)
        ),
        "browser_runs": sum(
            receipt.get("tool_name") == "sandbox.write_bytes"
            for receipt in run.get("tool_receipts", [])
            if isinstance(receipt, dict)
        ),
    }


def summary(
    client: httpx.Client, base_url: str, evaluation: dict[str, Any]
) -> dict[str, Any]:
    metrics = evaluation.get("metrics", {})
    return {
        "id": evaluation.get("id"),
        "status": evaluation.get("status"),
        "preflight_enabled": evaluation.get("request", {}).get(
            "builder_preflight_enabled"
        ),
        "success_rate": metrics.get("success_rate"),
        "average_score": metrics.get("average_score"),
        "browser_pass_rate": metrics.get("browser_pass_rate"),
        "feature_coverage_rate": metrics.get("feature_coverage_rate"),
        "average_agent_calls": metrics.get("average_agent_calls"),
        "average_duration_seconds": metrics.get("average_duration_seconds"),
        "runs": [
            {
                "case_id": item.get("case_id"),
                "passed": item.get("passed"),
                "score": item.get("score"),
                **run_detail(client, base_url, item["run_id"]),
            }
            for item in evaluation.get("results", [])
            if item.get("run_id")
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a paired Builder-preflight A/B evaluation.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    with httpx.Client(timeout=30) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        if not health.json().get("providers", {}).get("deepseek"):
            raise RuntimeError("DeepSeek provider is not configured")
        baseline = create(
            client,
            base_url,
            label=f"preflight-ab-off-{stamp}",
            preflight_enabled=False,
            baseline_id=None,
        )
        baseline = wait_for(client, base_url, baseline["id"], args.timeout)
        candidate = create(
            client,
            base_url,
            label=f"preflight-ab-on-{stamp}",
            preflight_enabled=True,
            baseline_id=baseline["id"],
        )
        candidate = wait_for(client, base_url, candidate["id"], args.timeout)
        result = {
            "design": {
                "provider": "deepseek",
                "cases": CASES,
                "skill_profile": "approved",
                "first_pass_only": False,
                "only_changed_factor": "builder_preflight_enabled",
            },
            "baseline": summary(client, base_url, baseline),
            "candidate": summary(client, base_url, candidate),
            "comparison": candidate.get("comparison", {}),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
