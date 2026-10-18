"""Recompute the public-facing report from immutable paired audit evidence."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation_sets" / "quotation-intent-v1"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-dir", type=Path, required=True)
    parser.add_argument("--heldout-dir", type=Path, required=True)
    args = parser.parse_args()
    destination = ROOT / "docs" / "quotation-intent-v1"
    cases = {case["id"]: case for case in load(DATASET / "cases.json")["cases"]}
    evidence = {}
    for split, directory in (("development", args.development_dir), ("heldout", args.heldout_dir)):
        result = load(directory / "results.json")
        audit = load(directory / "business-audit.json")
        if len(result["results"]) != result["planned_arm_count"]:
            raise RuntimeError("Incomplete generation results")
        evidence[split] = dict(path=str(directory), results=result, audit=audit)
    primary = evidence["heldout"]["audit"]["summary"]
    a, b = primary["arms"]["direct"], primary["arms"]["clarify"]
    n = a["planned_cases"]
    difference = b["business_pass"] - a["business_pass"]
    absolute_pp = 100 * difference / n
    subgroup = {}
    for category in ("sufficient", "underspecified"):
        ids = [case["id"] for case in cases.values()
               if case["split"] == "heldout" and case["initial_information"] == category]
        subgroup[category] = dict(
            cases=ids, planned=len(ids),
            direct=sum(r["end_to_end_pass"] for r in evidence["heldout"]["audit"]["rows"]
                       if r["arm"] == "direct" and r["case_id"] in ids),
            clarify=sum(r["end_to_end_pass"] for r in evidence["heldout"]["audit"]["rows"]
                        if r["arm"] == "clarify" and r["case_id"] in ids),
        )
    metrics = dict(
        generated_at=datetime.now(UTC).isoformat(), primary_split="heldout",
        independent_task_count=10, development_count=4, heldout_count=6,
        heldout=primary, heldout_by_initial_information=subgroup,
        observed_absolute_pass_difference_pp=absolute_pp,
        development=evidence["development"]["audit"]["summary"],
        provenance="Official documentation-derived requirements and synthetic seller preferences; not real customer feedback.",
        attribution="Clarification context, relevant question/answer release, typed intent and source-fact delivery are one intervention. Same Core. Does not isolate prompt wording or improve the base model.",
        measurement_notes=load(destination / "measurement-notes.json"),
    )
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    improvement = "观察到最终交付提升" if difference > 0 else "没有观察到最终交付提升" if difference == 0 else "询问组最终交付更差"
    lines = [
        "# 报价场景：结果与个人贡献", "",
        f"本轮结论：**{improvement}**。未参与调试的六条需求，直接生成通过 **{a['business_pass']}/{n}**，"
        f"先询问再生成通过 **{b['business_pass']}/{n}**，本轮多通过 **{difference}** 条，差 **{absolute_pp:.1f} 个百分点**。",
        "",
        "这里的通过是：原任务交付成功，且所有指定商品、客户、数量、日期、金额、税额、赠品和错误输入检查全部通过。"
        "以最终交付和独立业务检查为准。Core内部报错后自行修好只记返工，最终结果仍按同一规则评分。",
        "",
        "## 原先要解决什么", "",
        "销售可能只说一句“做一个报价演示”，却没有说清优惠门槛、客户适用范围或规则冲突时怎么办。"
        "直接生成容易做出能运行、但不符合销售真正要求的页面。项目目标是先获得必要规则，再交给同一个生成内核持续实现、测试与修复。",
        "",
        "## 你的贡献是什么", "",
        "1. **设计需求到交付的流程。** 将原始话术、模型实际提出的问题、固定的模拟销售回答、整理后的目标和Builder输入分别保存；"
        "只把问到的业务事实交给Builder，同时保留原始回答，避免信息在整理时丢失。",
        "2. **建立能判断对错的验收。** 将公开报价规则变成明确配置和可执行检查，覆盖边界、规则冲突、税额、买赠及非法输入；"
        "用独立的数值计算与真实浏览器读取结果，识别“已经生成但没有实现要求”的情况。",
        "3. **把效果比较做成可复核实验。** 固定四条调试题、六条新题、模型、生成预算和评分；保存失败、日志和耗时，"
        "保留信息充分的任务来检查多余询问，不靠修改新题答案制造提升。",
        "",
        "Codex CLI提供基础理解和写代码能力；上游项目及AI辅助实现应如实说明。你的可归因贡献是上述需求获取、上下文交付、执行与验收设计，"
        "不能把基础模型能力说成个人算法发明。",
        "",
        "## 主结果：六条未参与调试的新需求", "",
        "|指标|直接生成|先询问再生成|", "|---|---:|---:|",
        f"|完整业务通过|{a['business_pass']}/{n}|{b['business_pass']}/{n}|",
        f"|通过工程门并交付|{a['published']}/{n}|{b['published']}/{n}|",
        f"|已交付但完整复核未通过（含操作超时）|{a['published_but_business_failed']}|{b['published_but_business_failed']}|",
        f"|Core内部返工轮数|{a['core_revisions']}|{b['core_revisions']}|",
        f"|无需Core返工且业务通过|{a['first_pass_business']}/{n}|{b['first_pass_business']}/{n}|",
        f"|记录到的外层CLI调用（含询问）|{a['total_cli_calls']}|{b['total_cli_calls']}|",
        f"|其中询问调用|{a['intent_cli_calls']}|{b['intent_cli_calls']}|",
        f"|其中Core调用|{a['total_cli_calls']-a['intent_cli_calls']}|{b['total_cli_calls']-b['intent_cli_calls']}|",
        f"|端到端耗时中位数|{a['median_elapsed_seconds']:.1f}秒|{b['median_elapsed_seconds']:.1f}秒|",
        f"|指定浏览器路径通过|{a['passed_journeys']}/{a['planned_journeys']}|{b['passed_journeys']}/{b['planned_journeys']}|",
        f"|未执行路径（因任务未交付等）|{a['not_run_journeys']}|{b['not_run_journeys']}|",
        "",
        "外层CLI调用包含意图、Builder及显式验收子进程；不能当作完整模型计费。"
        "原生子智能体的内部调用若未完整回传，不能假装成本为零。两组Core调用均14次，返工均1轮；"
        "本轮提升在业务符合度，没有减少返工或调用成本。直接组报价10有长时间停顿，耗时不用于提速结论。",
        "",
        "|初始信息|新题数|直接生成通过|询问后通过|", "|---|---:|---:|---:|",
    ]
    for category, title in (("sufficient", "原话已说清"), ("underspecified", "原话缺少配置")):
        item = subgroup[category]
        lines.append(f"|{title}|{item['planned']}|{item['direct']}|{item['clarify']}|")
    lines.extend([
        "", "## 逐题结果", "",
        "调试表保留开发版本原始成绩：其中quotation-01的询问组被交接检查误拦截。"
        "该检查随后修正，单独复验该题12/12通过，未覆盖原成绩。"
        "六条保留题是在这项修正之后冻结实现并运行的，才是主结果。",
        "",
        "|用途|题目|初始信息|直接生成|先询问|", "|---|---|---|---|---|",
    ])
    for split in ("development", "heldout"):
        audit = evidence[split]["audit"]
        for case_id in sorted({row["case_id"] for row in audit["rows"]}):
            mapping = {r["arm"]: r for r in audit["rows"] if r["case_id"] == case_id}
            case = cases[case_id]
            def state(row):
                if row["case_id"] == "quotation-08" and row["arm"] == "clarify" and split == "heldout":
                    return "已交付；1条操作超时"
                return "全部通过" if row["end_to_end_pass"] else "未交付" if row["publication_status"] != "published" else "已交付但未通过"
            lines.append("|" + "|".join([
                "调试" if split == "development" else "保留新题",
                f"{case_id} {case['title']}",
                "充分" if case["initial_information"] == "sufficient" else "缺配置",
                state(mapping["direct"]), state(mapping["clarify"]),
            ]) + "|")
    lines.extend(["", "## 失败发生在哪里", ""])
    for row in evidence["heldout"]["audit"]["rows"]:
        if row["end_to_end_pass"]:
            continue
        title = f"{row['case_id']} / {'直接生成' if row['arm']=='direct' else '先询问'}"
        if row["publication_status"] != "published":
            source = next(r for r in evidence["heldout"]["results"]["results"]
                          if r["case_id"] == row["case_id"] and r["arm"] == row["arm"])
            lines.append(f"- {title}：未交付；最终记录：{source.get('error') or source['status']}。没有将未运行的业务路径计为通过。")
        else:
            failures = [journey for journey in row["journeys"] if journey["status"] != "passed"]
            if row["case_id"] == "quotation-08" and row["arm"] == "clarify":
                lines.append("- quotation-08 / 先询问：9/10条检查通过，切换商品再切回时填写数量发生2秒超时；"
                             "没有金额不符的记录。评分后仅作一次原源码、原超时设置的诊断回放，结果通过，未调用模型或修复页面。"
                             "因此当前不能确认业务逻辑缺陷，但原始完整通过数仍为5/6，不改为6/6。")
                continue
            example = failures[0] if failures else {}
            labels = dict(subtotal="小计", discount="优惠", tax="税额", total="应付", free_quantity="赠品数量")
            mismatches = example.get("mismatches") or []
            detail = "；".join(f"{labels.get(m['field'],m['field'])}应为{m['expected']}，页面显示{m['observed']}" for m in mismatches)
            detail = detail or str(example.get("error") or row.get("input_boundary"))
            lines.append(f"- {title}：{len(failures)}/{row['planned_journeys']}条检查未通过；示例 {example.get('id', '')}：{detail[:750]}。")
    lines.extend([
        "",
        "## 对测量问题的处理", "",
        "直接组报价09的读取边界警告误匹配了写入说明文件中的相对链接，所示命令没有读取私有答案。"
        "原标记保留；该题仍有8条金额检查失败，解释这项误报不改变1/6。",
        "",
        "直接组报价10记录11364.594秒，日志含约三小时空档，具体原因未确认。运行期间发生会话中断，"
        "不能由此推断操作系统休眠，也不能用总耗时差宣称询问模块更快。退出时另有异步子进程清理警告；"
        "完整时间线、警告和收尾检查单独保留。",
        "",
        "评分后诊断与原始评分分开保存，没有给Core反馈、重写结果或替换失败项。详见[测量说明](measurement-notes.md)。",
        "",
        "## 怎样理解这个提升", "",
        "两组使用同一个Core、同一组普通数据和同样的返工预算。询问组额外获得了实际询问到的销售配置，"
        "并将这些事实与整理后的目标交给Core。因此可归因于“需求获取与可靠传递”这一整套方法，不能单独归功于提示词措辞。",
        "",
        f"六条新题中，只有询问组通过的有{primary['clarification_only_wins']}条，只有直接组通过的有{primary['direct_only_wins']}条。"
        f"按题配对的双侧精确检验值为{primary['exact_paired_two_sided_p']:.5f}；"
        "它只作小样本诊断，不能把上百条相关操作当作上百个独立客户，也不能从单次运行推断稳定的总体收益。",
        "",
        "十条需求来自四份同一产品体系的官方业务文档；具体样例和销售回答是构造的。"
        "四条调试题不混入主结果，保留题没有在评分后修复或重写成绩。"
        "意图问答在独立实验runner运行，产品前端尚未接入真人问答会话。真人销售满意度、制作工时节约、客户转化率均未测量。",
        "",
        "## 可以怎样用于面试", "",
        "项目介绍应围绕：一句话需求缺少关键业务规则时，如何获得这些规则、可靠交给生成Agent，并通过独立验收验证最终交付。"
        "说明为什么仅测试页面能否打开会误判完成，再展示一组原始话术、追问回答、生成文件和浏览器检查。",
        "",
        f"可核实的结果表述：“基于公开报价业务规则构建10条评测需求，固定4条开发与6条保留测试；"
        f"在同模型、同生成预算下，完整业务通过从{a['business_pass']}/6变为{b['business_pass']}/6，"
        f"代价为外层CLI调用从{a['total_cli_calls']}次变为{b['total_cli_calls']}次。”"
        "这是公开规则和模拟销售回答上的单次小样本结果，尚不代表真实销售收益。",
        "",
        "## 证据与复现", "",
        "- [十条需求、公开来源和验收](../../evaluation_sets/quotation-intent-v1/需求与验收.md)",
        "- [数据集与实验说明](../../evaluation_sets/quotation-intent-v1/README.md)",
        "- [机器可读指标](metrics.json)",
        "- [每题可以直接核算的验收示例](逐题验收示例.md)",
        "- [调试结束与冻结决定](development-decision.json)",
        "- [本机环境记录](environment.json)",
        "- [一条需求的具体前后差异](案例说明.md)",
        "- [独立证据核对](independent-evidence-review.json)",
        "- [完整性验收记录](acceptance.json)",
        "- [运行收尾检查](cleanup.json)",
        f"- 调试完整结果：{args.development_dir.as_posix()}/business-audit.json",
        f"- 新题完整结果：{args.heldout_dir.as_posix()}/business-audit.json",
        "- 每个结果目录内保留context.json、frozen-code、逐轮stdin/stdout/stderr、问答、独立截图和源文件哈希。",
        "",
        "复算本报告：",
        "",
        f"    backend/.venv/Scripts/python.exe scripts/report_quotation_intent.py --development-dir {args.development_dir.as_posix()} --heldout-dir {args.heldout_dir.as_posix()}",
        "",
        "只核对留存证据、不重新生成或修改成绩：",
        "",
        "    backend/.venv/Scripts/python.exe scripts/verify_quotation_evidence.py",
    ])
    (destination / "结果与贡献.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(heldout_direct=a["business_pass"], heldout_clarify=b["business_pass"],
                          difference=difference, report=str(destination / "结果与贡献.md")), ensure_ascii=False))


if __name__ == "__main__":
    main()
