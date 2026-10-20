"""Zero-model development checks for field-based seller fact delivery.

The 32 wordings are predeclared inputs. Their correct field identifiers are
provided by this check, so the result is not an LLM semantic mapping score.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from demopilot.business_fields import BusinessFacts, Clarification  # noqa: E402

FIELD_BY_TOPIC = {
    "catalogue": "catalogue", "pricing": "pricing_rule",
    "workflow": "workflow", "shipping": "shipping",
}
FORMS = {
    "catalogue": {
        "canonical": ["商品单价是多少？", "产品价格分别是多少？"],
        "paraphrase": ["各款货品多少钱？", "给我一份价目表。", "每件货物怎么收费？", "A/B/C各卖多少？", "三款套餐分别多少钱？", "请给我每件货物的标价。"],
    },
    "pricing": {
        "canonical": ["优惠怎么算？", "请说明定价规则。"],
        "paraphrase": ["整单金额怎样算出来？", "这一单的钱按什么规则收？", "金额的计算办法是什么？", "可以少付多少、按什么条件少付？", "付款金额的计算顺序是什么？", "哪些条件会改变应付金额？"],
    },
    "workflow": {
        "canonical": ["审批流程是什么？", "谁负责审批，先后顺序是什么？"],
        "paraphrase": ["谁来批这张报价？", "这单先给哪个人签字？", "谁拥有最后拍板权？", "报批要经过哪些岗位？", "从提交到成交都要走哪些人？", "报价单该交给哪位负责人过目？"],
    },
    "shipping": {
        "canonical": ["运费是多少？", "配送如何收费？"],
        "paraphrase": ["送货要付多少钱？", "快递费分别收多少？", "物流收费标准是什么？", "寄过来另收多少？", "送上门的费用怎么收？", "发货这笔钱是多少？"],
    },
}


def development_cases():
    data = json.loads((ROOT / "evaluation_sets/sales-benchmark-v3/cases.json").read_text("utf-8"))
    # Never open private acceptance files or inspect/use final-case payloads.
    cases = [case for case in data["cases"] if case["split"] == "development"]
    split = json.loads((ROOT / "evaluation_sets/sales-benchmark-v3/split.json").read_text("utf-8"))
    if {case["id"] for case in cases} != set(split["development"]) or len(cases) != 60:
        raise ValueError("Expected the frozen 60 development fact records")
    return cases


def store_for(case):
    return BusinessFacts(case["expected_plan"], {
        item["topic"]: item["answer"] for item in case["seller_answers"]
    })


def legacy_selector(revision):
    text = subprocess.check_output(
        ["git", "show", f"{revision}:scripts/run_sales_benchmark_pilot.py"], cwd=ROOT,
    ).decode("utf-8")
    node = next(node for node in ast.parse(text).body
                if isinstance(node, ast.FunctionDef) and node.name == "answers_for")
    source = ast.get_source_segment(text, node)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<readonly-legacy-selector>", "exec"), namespace)  # noqa: S102 -- Execute only the trusted fixed Git function; never question text.
    return namespace["answers_for"], hashlib.sha256(source.encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_matrix(output, revision="e6bed15"):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    guards = [
        ROOT / "docs/sales-benchmark-v3/final-staged/CAMPAIGN.json",
        ROOT / "docs/sales-benchmark-v3/final-staged/checkpoint.json",
        ROOT / "docs/engineering/shared-contract-repair-20261020/WORKFLOW_STATE.json",
    ]
    before = {str(path.relative_to(ROOT)): sha(path) for path in guards if path.is_file()}
    cases = development_cases()
    old, old_hash = legacy_selector(revision)
    rows = []
    for case in cases:
        store = store_for(case)
        for topic, groups in FORMS.items():
            for group, questions in groups.items():
                for question in questions:
                    field = FIELD_BY_TOPIC[topic]
                    request = Clarification(question=question, field_ids=[field], reason="missing")
                    response = store.reply([request])
                    facts = response["facts"]
                    selected = old([question], case, set())
                    correct = len(facts) == 1 and facts[0]["field_id"] == field
                    correct = correct and facts[0]["value"] == case["expected_plan"][field]
                    correct = correct and facts[0]["source"]["topic"] == topic
                    rows.append({
                        "case_id": case["id"], "topic": topic, "form": group,
                        "question": question, "provided_field_ids": [field],
                        "old_target_fact_released": any(item["topic"] == topic for item in selected),
                        "old_other_topics": [item["topic"] for item in selected if item["topic"] != topic],
                        "new_exact_fact_only": correct,
                        "new_repeat_idempotent": response == store.reply([request]),
                        "new_response": response,
                    })
    after = {path: sha(ROOT / path) for path in before}
    groups = []
    for form in ("canonical", "paraphrase"):
        subset = [row for row in rows if row["form"] == form]
        groups.append({
            "form": form, "unique_wordings": len({row["question"] for row in subset}),
            "fact_record_wording_combinations": len(subset),
            "old_target_fact_released": sum(row["old_target_fact_released"] for row in subset),
            "new_exact_fact_only": sum(row["new_exact_fact_only"] for row in subset),
            "new_repeat_idempotent": sum(row["new_repeat_idempotent"] for row in subset),
        })
    summary = {
        "kind": "given-field-id-protocol-controls-not-llm-intent-accuracy",
        "development_fact_records": len(cases), "unique_predeclared_wordings": 32,
        "combinations": len(rows), "groups": groups,
        "all_expected": all(row["new_exact_fact_only"] and row["new_repeat_idempotent"] for row in rows)
                        and before == after,
        "old_revision": revision, "old_selector_sha256": old_hash,
        "new_source_sha256": sha(ROOT / "backend/src/demopilot/business_fields.py"),
        "forms_source_sha256": sha(Path(__file__)),
        "protected_records_before": before, "protected_records_after": after,
        "historical_records_unchanged": before == after,
        "cli_calls": 0, "model_calls": 0, "final_cases_executed": 0,
        "boundary": "The check supplies correct field_ids. It proves wording-independent deterministic delivery and idempotent replay; it does not prove an LLM can map these 32 wordings or estimate accuracy on 1920 independent requirements.",
    }
    (output / "matrix.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--old-revision", default="e6bed15")
    args = parser.parse_args()
    result = run_matrix(args.output, args.old_revision)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["all_expected"] else 1)
