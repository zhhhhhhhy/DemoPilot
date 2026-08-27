from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime

import httpx


CASES = ["retail-01", "logistics-01", "procurement-01"]
TERMINAL = {"completed", "failed", "cancelled"}


def wait_for(client: httpx.Client, base_url: str, evaluation_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
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
    provider: str,
    profile: str,
    label: str,
    baseline_id: str | None,
) -> dict:
    payload = {
        "provider": provider,
        "case_ids": CASES,
        "case_limit": len(CASES),
        "concurrency": 1,
        "version_label": label,
        "baseline_id": baseline_id,
        "skill_profile": profile,
        "first_pass_only": True,
        "thresholds": {
            "min_success_rate": 0,
            "min_average_score": 0,
            "min_browser_pass_rate": 0,
            "min_feature_coverage_rate": 0,
            "max_average_agent_calls": 18,
        },
    }
    response = client.post(f"{base_url}/api/evaluations", json=payload)
    response.raise_for_status()
    return response.json()


def summary(evaluation: dict) -> dict:
    metrics = evaluation.get("metrics", {})
    return {
        "id": evaluation.get("id"),
        "status": evaluation.get("status"),
        "profile": evaluation.get("request", {}).get("skill_profile"),
        "first_pass_success_rate": metrics.get("first_pass_success_rate"),
        "first_pass_average_score": metrics.get("first_pass_average_score"),
        "browser_pass_rate": metrics.get("browser_pass_rate"),
        "feature_coverage_rate": metrics.get("feature_coverage_rate"),
        "average_agent_calls": metrics.get("average_agent_calls"),
        "average_duration_seconds": metrics.get("average_duration_seconds"),
        "runs": [
            {
                "case_id": item.get("case_id"),
                "run_id": item.get("run_id"),
                "first_pass_passed": item.get("first_pass_passed"),
                "first_pass_score": item.get("first_pass_score"),
                "issues": item.get("issues", [])[:3],
            }
            for item in evaluation.get("results", [])
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a same-provider, same-case first-pass Skill A/B evaluation."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--timeout", type=float, default=2700)
    parser.add_argument(
        "--baseline-id",
        help="Reuse a completed baseline with the same provider and cases.",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    with httpx.Client(timeout=30) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        if not health.json().get("providers", {}).get(args.provider):
            raise RuntimeError(f"provider is not configured: {args.provider}")

        if args.baseline_id:
            baseline = wait_for(client, base_url, args.baseline_id, args.timeout)
        else:
            baseline = create(
                client,
                base_url,
                provider=args.provider,
                profile="baseline",
                label=f"skill-ab-baseline-{stamp}",
                baseline_id=None,
            )
            baseline = wait_for(client, base_url, baseline["id"], args.timeout)
        candidate = create(
            client,
            base_url,
            provider=args.provider,
            profile="candidate",
            label=f"skill-ab-candidate-{stamp}",
            baseline_id=baseline["id"],
        )
        candidate = wait_for(client, base_url, candidate["id"], args.timeout)

    result = {
        "cases": CASES,
        "baseline": summary(baseline),
        "candidate": summary(candidate),
        "comparison": candidate.get("comparison", {}),
        "skill_promotion": candidate.get("skill_promotion", {}),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["skill_promotion"].get("eligible") else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (httpx.HTTPError, RuntimeError, TimeoutError) as exc:
        print(f"Skill A/B failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
