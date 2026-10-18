"""Freeze a small raw-sales intent pilot from authored v1 cases.

The gold file is evaluator-only. It is never copied into a Core workspace.
The pilot intentionally measures downstream release behavior of raw versus
confirmed structured input; it does not claim that the current form is an AI
intent recognizer.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation_sets" / "codex-cli-v1" / "cases.json"
OUT = ROOT / "evaluation_sets" / "sales-intent-v1"
SELECTED = [
    "simple-quote-generator-01",
    "medium-lead-followup-01",
    "hard-procurement-approval-01",
]


def main() -> int:
    source = {item["id"]: item for item in json.loads(SOURCE.read_text(encoding="utf-8"))["cases"]}
    cases: list[dict[str, object]] = []
    gold: list[dict[str, object]] = []
    for case_id in SELECTED:
        case = source[case_id]
        raw = (
            f"我是{case['audience']}，现在要给客户演示一个{case['industry']}场景。"
            f"客户希望{case['scenario']}。先做一个能在浏览器里完整讲清楚的本地演示，"
            "不要接真实系统，具体页面和步骤请你先帮我梳理。"
        )
        cases.append(
            {
                "id": case_id,
                "source_case_id": case_id,
                "difficulty": case["difficulty"],
                "raw_sales_brief": raw,
                "dataset": "codex-cli-v1",
                "acceptance_case_ref": f"testdata/{case_id}/acceptance.json",
                "intent_module_status": "manual-confirmation-only",
            }
        )
        gold.append(
            {
                "case_id": case_id,
                "actor": case["audience"],
                "problem": case["scenario"],
                "desired_outcome": case["goal"],
                "must_haves": case["must_haves"],
                "flow_steps": case["flow_steps"],
                "acceptance": case["acceptance_criteria"],
                "constraints": ["只交付本地静态演示", "不得连接外部服务"],
                "non_goals": ["不连接客户生产系统", "不写入真实业务数据"],
                "business_gold_source": f"evaluation_sets/codex-cli-v1/cases.json#{case_id}.browser_contract",
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gold").mkdir(exist_ok=True)
    (OUT / "cases.json").write_text(
        json.dumps(
            {
                "schema_version": "sales-intent-v1",
                "cases": cases,
                "gold_policy": "gold/intent-gold.json is evaluator-only and is not mounted into Core workspace",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "gold" / "intent-gold.json").write_text(
        json.dumps({"schema_version": "sales-intent-gold-v1", "cases": gold}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
