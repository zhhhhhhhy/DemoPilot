from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

DEFAULT_CASE_IDS = [
    "insurance-01",
    "hospitality-01",
    "agriculture-01",
    "aviation-01",
    "automotive-01",
    "construction-01",
]
TERMINAL = {"completed", "failed", "cancelled"}


def case_batches(case_ids: list[str]) -> list[list[str]]:
    return [case_ids[index : index + 3] for index in range(0, len(case_ids), 3)]


def wait_for(
    client: httpx.Client, base_url: str, evaluation_id: str, timeout: float
) -> dict[str, Any]:
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


def create_batch(
    client: httpx.Client,
    base_url: str,
    *,
    case_ids: list[str],
    label: str,
) -> dict[str, Any]:
    response = client.post(
        f"{base_url}/api/evaluations",
        json={
            "provider": "deepseek",
            "case_ids": case_ids,
            "case_limit": len(case_ids),
            "concurrency": 1,
            "version_label": label,
            "skill_profile": "approved",
            "first_pass_only": False,
            "builder_preflight_enabled": True,
            "thresholds": {
                "min_success_rate": 0.66,
                "min_average_score": 70,
                "min_browser_pass_rate": 0.66,
                "min_feature_coverage_rate": 0.8,
                "max_average_agent_calls": 18,
            },
        },
    )
    response.raise_for_status()
    return response.json()


def compact(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": evaluation.get("id"),
        "status": evaluation.get("status"),
        "verdict": evaluation.get("verdict"),
        "metrics": evaluation.get("metrics"),
        "results": [
            {
                "case_id": item.get("case_id"),
                "run_id": item.get("run_id"),
                "status": item.get("status"),
                "passed": item.get("passed"),
                "score": item.get("score"),
                "failure_category": item.get("failure_category"),
                "browser_status": item.get("browser_status"),
                "feature_coverage": item.get("feature_coverage"),
                "agent_calls": item.get("agent_calls"),
                "revision_count": item.get("revision_count"),
                "duration_seconds": item.get("duration_seconds"),
                "issues": item.get("issues"),
            }
            for item in evaluation.get("results", [])
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run selected DemoPilot cases through the real DeepSeek provider."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--label-prefix", default="expanded-deepseek")
    parser.add_argument("--case-ids", nargs="+", default=DEFAULT_CASE_IDS)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    selected_case_ids = list(args.case_ids)
    if len(selected_case_ids) != len(set(selected_case_ids)):
        raise ValueError("case ids must be unique within one expansion run")
    batches = case_batches(selected_case_ids)

    with httpx.Client(timeout=30) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        if not health.json().get("providers", {}).get("deepseek"):
            raise RuntimeError("DeepSeek provider is not configured")

        known_ids = {
            item["id"]
            for item in client.get(f"{base_url}/api/evaluation-cases").raise_for_status().json()
        }
        requested_ids = set(selected_case_ids)
        missing = sorted(requested_ids - known_ids)
        if missing:
            raise RuntimeError(f"API does not expose the expanded cases: {missing}")

        evaluations = []
        for index, batch in enumerate(batches, start=1):
            created = create_batch(
                client,
                base_url,
                case_ids=batch,
                label=f"{args.label_prefix}-{stamp}-b{index}",
            )
            completed = wait_for(client, base_url, created["id"], args.timeout)
            evaluations.append(compact(completed))

    result = {
        "design": {
            "provider": "deepseek",
            "unique_cases": len(selected_case_ids),
            "batches": batches,
            "concurrency": 1,
            "skill_profile": "approved",
            "builder_preflight_enabled": True,
        },
        "evaluations": evaluations,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
