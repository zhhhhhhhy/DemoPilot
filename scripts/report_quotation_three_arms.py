"""Report appended full-information control without rewriting original A/B."""
from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from run_quotation_full_rules import ARM, DATASET, OLD_DEV, OLD_HELD, ROOT, base, supplied_facts

DOCS = ROOT / "docs/quotation-information-ablation-v1"
LABELS = {"direct": "A：一句话直接生成", "clarify": "B：追问并整理意图", ARM: "C：完整规则直接生成"}


def summarize(runs, audits, split):
    output = {}
    for arm in LABELS:
        rr = [r for r in runs if r["arm"] == arm and r["split"] == split]
        aa = [r for r in audits if r["arm"] == arm and r["split"] == split]
        if len(rr) != (6 if split == "heldout" else 4) or len(aa) != len(rr):
            raise RuntimeError("Incomplete case-arm denominator")
        output[arm] = dict(cases=len(rr), published=sum(r["publication_status"] == "published" for r in rr),
            complete_pass=sum(r["end_to_end_pass"] for r in aa),
            core_calls=sum(r["agent_calls"] for r in rr), intent_calls=sum(r["intent_cli_calls"] for r in rr),
            total_calls=sum(r["total_cli_calls"] for r in rr), repairs=sum(r["revision_count"] for r in rr),
            planned_journeys=sum(r["planned_journeys"] for r in aa),
            executed_journeys=sum(len(r["journeys"]) for r in aa),
            passed_journeys=sum(r.get("passed_journeys", 0) for r in aa),
            not_run_journeys=sum(r.get("not_run_journeys", 0) for r in aa),
            monetary_mismatch_journeys=sum(bool(j.get("mismatches")) for r in aa for j in r["journeys"]),
            timeout_journeys=sum("Timeout" in j.get("error", "") for r in aa for j in r["journeys"]),
            total_wall_seconds=round(sum(r["elapsed_seconds"] for r in rr), 3))
    return output


def contrast(audits, left, right):
    pairs = []
    for case in base.all_cases():
        if case["split"] != "heldout":
            continue
        aa = {r["arm"]: r for r in audits if r["case_id"] == case["id"]}
        pairs.append(dict(case_id=case["id"], left=aa[left]["end_to_end_pass"], right=aa[right]["end_to_end_pass"]))
    gains = sum(p["right"] and not p["left"] for p in pairs)
    losses = sum(p["left"] and not p["right"] for p in pairs)
    n = gains + losses
    p = min(1, 2 * sum(math.comb(n, k) for k in range(min(gains, losses) + 1)) / 2**n) if n else 1.0
    return dict(left_arm=left, right_arm=right, right_only=gains, left_only=losses, net_complete_pass=gains-losses,
                exact_paired_two_sided_p=p, pairs=pairs, inference="Descriptive retrospective small-sample comparison, not a controlled population causal estimate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-rules-dir", type=Path, required=True)
    args = parser.parse_args()
    run_rows, audit_rows = [], []
    for directory in (OLD_DEV, OLD_HELD, args.full_rules_dir):
        results = base.load_json(directory / "results.json")
        if len(results["results"]) != results["planned_arm_count"]:
            raise RuntimeError("All planned outcomes required")
        run_rows.extend(results["results"])
        audit_rows.extend(base.load_json(directory / "business-audit.json")["rows"])
    if len(run_rows) != 30 or len({(r["case_id"], r["arm"]) for r in run_rows}) != 30:
        raise RuntimeError("Exactly ten cases x three arms required")
    context = base.load_json(args.full_rules_dir / "context.json")
    if any(base.sha(ROOT / p) != h for p, h in context["historical_sha256"].items()):
        raise RuntimeError("Historical A/B evidence changed")
    primary, development = summarize(run_rows, audit_rows, "heldout"), summarize(run_rows, audit_rows, "development")
    parity = []
    for case in base.all_cases():
        if case["split"] != "heldout":
            continue
        facts = supplied_facts(case)
        released = base.load_json(OLD_HELD / case["id"] / "clarify/intent/released-topics.json")["facts"]
        parity.append(dict(case_id=case["id"], initial_information=case["initial_information"],
            c_facts=facts, b_released_facts=released,
            all_c_facts_were_released_to_b=all(fact in released for fact in facts),
            original_already_complete_control=case["initial_information"] == "sufficient",
            b_uses_typed_goal_and_requirements=True, c_uses_typed_goal_and_requirements=False))
    A, B, C = (primary[key] for key in LABELS)
    if C["complete_pass"] >= B["complete_pass"] and C["complete_pass"] > A["complete_pass"]:
        attribution = "完整规则直接交给Core也能取得提升；本轮没有显示意图整理比直接给完整规则带来更多完整通过。已有收益主要支持获取缺失信息的价值。"
    elif C["complete_pass"] < B["complete_pass"]:
        attribution = "询问整理组的完整通过数高于完整规则直接组，出现处理方式可能有益的信号；需要结合逐题缺陷、信息一致性与单次运行波动解释，不能据此认定额外收益已经成立。"
    else:
        attribution = "本轮完整信息对照未显示稳定提升；保留全部失败，当前不能把原有差异明确归因于补充信息或意图整理。"
    metrics = dict(generated_at=datetime.now(UTC).isoformat(), primary_cases=6, total_cases=10,
        primary=primary, development=development, information_parity=parity,
        contrasts=dict(information=contrast(audit_rows,"direct",ARM),processing=contrast(audit_rows,ARM,"clarify")),
        attribution=attribution,
        design="C added after A/B outcomes were known; same frozen Core/scorer and configured budgets; original six primary cases reused, no new unseen claim.",
        limitations=["Scripted seller and one vendor's four public documents, not real sales feedback", "Single execution per task/arm; no independent repeated seeds or concurrent randomization", "B08 original timeout remains failed despite successful diagnostic replay", "A10 long interruption makes timing comparisons unsuitable", "Native child usage may be incomplete; outer CLI calls are not billed cost", "No OS-level confidentiality isolation; frozen tool guard can misclassify documentation links"])
    DOCS.mkdir(parents=True, exist_ok=True)
    base.write_json(DOCS / "metrics.json", metrics)
    base.write_json(DOCS / "information-parity.json", dict(primary_cases=parity, note="B07 already had complete rules in the original brief; C repeats the seller rule without an intent transform."))
    lines = ["# 报价三组比较：信息补全与意图整理", "",
        f"主结果：同六条原保留题，A一句话通过{A['complete_pass']}/6，B询问整理通过{B['complete_pass']}/6，C完整规则直接生成通过{C['complete_pass']}/6。", "", attribution, "",
        "## 三组究竟差在哪里", "",
        "- A：原始一句话交给Core，没有额外销售规则。",
        "- B：模型实际追问，得到模拟销售回答，再生成结构化目标、必须功能和验收描述，同时保留原回答。",
        "- C：原话后直接附上全部模拟销售规则；不调用意图模型，不生成结构化目标或业务验收列表。除业务信息字段外，其余输入与A相同。", "",
        "C的完整规则来自原先固定的销售回答，没有复制B模型整理结果，没有加入私有测试输入或预期计算结果。两组收到的普通商品、客户数据和工程要求一致。", "",
        "## 六条主比较结果", "",
        "|指标|A 一句话|B 询问整理|C 完整规则直接给|", "|---|---:|---:|---:|",
        f"|完整通过|{A['complete_pass']}/6|{B['complete_pass']}/6|{C['complete_pass']}/6|",
        f"|工程交付|{A['published']}/6|{B['published']}/6|{C['published']}/6|",
        f"|浏览器路径通过|{A['passed_journeys']}/68|{B['passed_journeys']}/68|{C['passed_journeys']}/68|",
        f"|Core调用|{A['core_calls']}|{B['core_calls']}|{C['core_calls']}|",
        f"|意图调用|{A['intent_calls']}|{B['intent_calls']}|{C['intent_calls']}|",
        f"|全部外层CLI调用|{A['total_calls']}|{B['total_calls']}|{C['total_calls']}|",
        f"|Core返工轮数|{A['repairs']}|{B['repairs']}|{C['repairs']}|", "",
        "Core条件保持gpt-6.1-sol、medium、每次CLI配置300秒、最多两次返工，最多两个任务并行。B的询问调用是额外成本，没有为C安排无意义的调用来凑数。", "",
        "|题目|A|B|C|", "|---|---|---|---|"]
    for case in base.all_cases():
        if case["split"] != "heldout": continue
        aa={r["arm"]:r for r in audit_rows if r["case_id"]==case["id"]}
        def outcome(arm):
            row=aa[arm]
            if row["end_to_end_pass"]: return "完整通过"
            if arm=="clarify" and case["id"]=="quotation-08": return "1条操作超时，原分保留"
            return f"未完整通过（{row.get('passed_journeys',0)}/{row['planned_journeys']}条通过）"
        lines.append(f"|{case['id']} {case['title']}|{outcome('direct')}|{outcome('clarify')}|{outcome(ARM)}|")
    lines += ["", "## 四条调试题另外列，不混入主成绩", "",
        f"A为{development['direct']['complete_pass']}/4，B为{development['clarify']['complete_pass']}/4，C为{development[ARM]['complete_pass']}/4。",
        "B调试题01的原始失败发生在交接校验修复前，仍保留原成绩；其单独12/12修复回归不替换本表，也不用于推断三组效果。", "",
        "## 完整规则组未通过的具体位置", ""]
    failed = [r for r in audit_rows if r["arm"]==ARM and not r["end_to_end_pass"]]
    if not failed: lines.append("十条均完整通过，未发现指定数据上的最终业务失败。")
    for row in failed:
        errors=[dict(id=j['id'],error=j.get('error'),mismatches=j.get('mismatches')) for j in row['journeys'] if j['status']!='passed']
        lines.append(f"- {row['case_id']}：{row['publication_status']}；{row.get('passed_journeys',0)}/{row['planned_journeys']}通过。具体：{json.dumps(errors,ensure_ascii=False)[:1600]}。输入边界检查：{row['input_boundary']['status']}。")
    lines += ["", "## 哪些贡献现在可以写进简历", "",
        "可以写：设计主动追问与业务事实完整传递流程，将销售一句话中缺失的规则变成可执行输入；构建有公开业务依据、明确答案、独立浏览器检查和保留测试的评测。", "",
        f"可核实表述：基于公开报价规则构建10条模拟销售需求，固定4条开发、6条保留；原话直接生成{A['complete_pass']}/6，主动追问整理{B['complete_pass']}/6，完整规则直接生成{C['complete_pass']}/6；用追加对照检验信息获取与意图整理的作用。", "",
        attribution, "",
        "不写尚未证实的意图处理独立准确率收益、真实销售工时或转化收益，也不把基础模型能力归为个人算法。若人工本就给足规则，主动追问未必带来额外收益。", "",
        "## 解释结果必须保留的边界", "",
        "这是在原A/B成绩已知之后追加的C组，沿用原六条保留题；它们对当前追加设计已非全新未知题。保持了同一份Core、评分程序和配置预算，但没有同期随机三组或重复运行，远程模型服务的内部变化不可观察。", "",
        "B的报价08唯一失败是2秒操作超时，原样诊断通过，但原评分仍是5/6；不能把该题差异当作意图整理损害业务能力的证据。A的报价10有长时间停顿，不作速度结论。A09旧守卫误匹配说明链接，但另有金额错误，原成绩不改。", "",
        "模型和返工预算指相同的Core配置；实际询问开销另外计入。外层CLI次数不能换算完整账单。浏览器路径属于同一批任务内相关检查，不能当成独立客户样本。产品前端真人问答与真实销售反馈尚未验证。", "",
        "## 证据", "",
        "- [三组可复算指标](metrics.json)", "- [业务信息是否对齐](information-parity.json)",
        "- [原始两组结果](../quotation-intent-v1/结果与贡献.md)",
        "- [完整规则组原始结果](../../evaluation_sets/quotation-intent-v1/results/full-rules-20261016/results.json)",
        "- [完整规则组独立验收](../../evaluation_sets/quotation-intent-v1/results/full-rules-20261016/business-audit.json)", "",
        "复算报告：", "", "    backend/.venv/Scripts/python.exe scripts/report_quotation_three_arms.py --full-rules-dir evaluation_sets/quotation-intent-v1/results/full-rules-20261016"]
    (DOCS / "结果与简历贡献.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(dict(primary=primary, attribution=attribution), ensure_ascii=False))


if __name__ == "__main__":
    main()
