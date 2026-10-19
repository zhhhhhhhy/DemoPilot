"""Read-only report from completed pilot evidence; never launches a model."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def audit_cost(directory):
    calls = []
    for path in sorted(directory.rglob("stdout.jsonl")):
        usage = []
        events = []
        transport_signals = set()
        for line in path.read_text("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event.get("usage"), dict):
                usage.append(event["usage"])
            events.append(event.get("type"))
            message = str(event.get("message", "")) + str(event.get("error", ""))
            for signature, category in (
                (
                    "workspace routing discovery failed",
                    "workspace_routing_discovery_failed",
                ),
                ("tls handshake eof", "tls_handshake_eof"),
                (
                    "Connection failed: error sending request",
                    "request_transport_failure",
                ),
            ):
                if signature in message:
                    transport_signals.add(category)
        relative = path.relative_to(directory).as_posix()
        totals = {
            k: sum(u.get(k, 0) for u in usage)
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        }
        calls.append(
            dict(
                relative=relative,
                kind="intake"
                if relative.startswith("intent/")
                else "core"
                if "/cli/" in relative
                else "other",
                usage=totals if usage else None,
                completed="turn.completed" in events,
                transport_signals=sorted(transport_signals),
            )
        )
    return dict(
        calls=len(calls),
        intake=sum(c["kind"] == "intake" for c in calls),
        core=sum(c["kind"] == "core" for c in calls),
        usage_complete=sum(c["usage"] is not None for c in calls),
        missing_usage=sum(c["usage"] is None for c in calls),
        failed_root_calls=sum(not c["completed"] for c in calls),
        last_failed_cli_transport_signals=(
            calls[-1]["transport_signals"]
            if calls and not calls[-1]["completed"]
            else []
        ),
        tokens={
            k: sum((c["usage"] or {}).get(k, 0) for c in calls)
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        monetary_cost=None,
    )


def report(output, destination):
    raw = read(output / "results.json")
    context = read(output / "context.json")
    execution_split = context.get("execution_split", "development")
    rows = raw["rows"]
    out = []
    assert len(rows) == len(context["pilot_ids"]) and {
        r["case_id"] for r in rows
    } == set(context["pilot_ids"])
    for row in sorted(rows, key=lambda r: r["case_id"]):
        r = {
            k: row.get(k)
            for k in [
                "case_id",
                "difficulty",
                "family",
                "session_id",
                "status",
                "stage",
                "delivery_pass",
                "final_functional_pass",
                "confirmation_semantics_match",
                "elapsed_seconds",
                "core_calls",
                "internal_core_repairs",
                "independent_check",
                "iterations",
            ]
        }
        r["cost"] = (
            audit_cost(output / "sales-core/sessions" / row["session_id"])
            if row["session_id"]
            else dict(calls=0, intake=0, core=0, usage_complete=0, tokens={})
        )
        target = output / "case-results" / row["case_id"]
        confirmation = target / "confirmation.json"
        terminal = target / "session-terminal.json"
        r["observed_differences"] = []
        if confirmation.exists():
            c = read(confirmation)
            for key in [
                "workflow",
                "pricing_rule",
                "shipping",
                "approval_threshold",
                "valid_until",
            ]:
                if c["actual"].get(key) != c["expected"].get(key):
                    r["observed_differences"].append(
                        dict(
                            field=key,
                            actual=c["actual"].get(key),
                            expected=c["expected"].get(key),
                        )
                    )
        if terminal.exists():
            s = read(terminal)
            r["remaining_questions"] = s["questions"]
            dialogue = "\n".join(
                m["content"] for m in s["messages"] if m["role"] == "user"
            )
            r["manager_actor_absent_from_delivered_sales_facts"] = (
                "经理" not in dialogue
            )
        r["failure_reason"] = row.get("failure_reason")
        r["stage_in_chinese"] = {
            "intent_contract": "意图整理后规则不符，未启动Core",
            "intake": "问询未完成，未启动Core",
            "core": "Core终态未发布",
            "publication": "已发布，按最终检查评分",
        }.get(row["stage"], row["stage"])
        r["failure_domain"] = None
        if not r["delivery_pass"]:
            if r["cost"].get("last_failed_cli_transport_signals"):
                r["failure_domain"] = "cli_transport"
                location = "意图调用" if row["stage"] == "intake" else "Core调用"
                r["stage_in_chinese"] = f"{location}：CLI连接或路由失败"
            elif row["status"] == "published":
                r["failure_domain"] = (
                    "final_function"
                    if not row["final_functional_pass"]
                    else "served_assets"
                )
                r["stage_in_chinese"] = (
                    "发布后功能检查失败"
                    if not row["final_functional_pass"]
                    else "发布资源不一致"
                )
            else:
                r["failure_domain"] = row["stage"]
        out.append(r)
    costs = [r["cost"] for r in out]
    elapsed = sorted(r["elapsed_seconds"] for r in out)
    delivered_elapsed = sorted(r["elapsed_seconds"] for r in out if r["delivery_pass"])
    summary = dict(
        planned=len(rows),
        delivered=sum(r["delivery_pass"] for r in rows),
        published=sum(r["status"] == "published" for r in rows),
        final_failure_stages=dict(
            Counter(r["stage_in_chinese"] for r in out if not r["delivery_pass"])
        ),
        published_defects=sum(
            r["status"] == "published" and not r["final_functional_pass"] for r in rows
        ),
        root_cli_calls=sum(c["calls"] for c in costs),
        intake_calls=sum(c["intake"] for c in costs),
        core_calls=sum(c["core"] for c in costs),
        calls_with_reported_usage=sum(c["usage_complete"] for c in costs),
        calls_without_reported_usage=sum(
            c["calls"] - c["usage_complete"] for c in costs
        ),
        final_failure_domains=dict(
            Counter(r["failure_domain"] for r in out if not r["delivery_pass"])
        ),
        reported_root_tokens={
            k: sum(c["tokens"].get(k, 0) for c in costs)
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        median_elapsed_seconds=round(
            (elapsed[(len(elapsed) - 1) // 2] + elapsed[len(elapsed) // 2]) / 2, 2
        ),
        sum_elapsed_seconds=round(sum(elapsed), 2),
        delivered_task_elapsed_seconds=delivered_elapsed,
        delivered_median_seconds=round(statistics.median(delivered_elapsed), 2)
        if delivered_elapsed
        else None,
        final_browser_paths=raw["summary"]["final_browser_paths"],
        heldout_executed=0,
        validation_executed=len(rows) if execution_split == "validation" else 0,
        execution_split=execution_split,
        anomalies_live_executed=0,
        monetary_cost=None,
        boundary=f"Fixed {execution_split} product cohort, not A/B/C, human-gold or production benefit. Root token report only; cached input is a subset of input, not extra. Original result files retained unchanged.",
        measurement_note="Derived cost audit normalizes Windows path separators; original per-kind counts in runner v1 may be zero due to separator mismatch. Total raw process count/token usage unaffected.",
    )
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "pilot-summary.json").write_text(
        json.dumps(dict(summary=summary, cases=out), ensure_ascii=False, indent=2)
        + "\n",
        "utf-8",
    )
    lines = [
        f"# {len(rows)}题{'阶段验收' if execution_split == 'validation' else '开发复测'}结果",
        "",
        f"完整交付：{summary['delivered']}/{summary['planned']}；发布：{summary['published']}/{summary['planned']}。",
        "",
        "| 题目 | 难度 | 最终环节 | 交付 | CLI调用 | 意图/Core | 耗时秒 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {r['case_id']} | {r['difficulty']} | {r['stage_in_chinese']} | {'通过' if r['delivery_pass'] else '未通过'} | {r['cost']['calls']} | {r['cost']['intake']}/{r['cost']['core']} | {r['elapsed_seconds']} |"
        for r in out
    ]
    t = summary["reported_root_tokens"]
    lines += [
        "",
        "## 消耗",
        f"根CLI进程{summary['root_cli_calls']}次，其中意图{summary['intake_calls']}次、Core{summary['core_calls']}次。",
        f"报告输入token {t['input_tokens']}（其中缓存{t['cached_input_tokens']}），输出{t['output_tokens']}；货币账单未知。",
        f"{summary['calls_without_reported_usage']}次根调用缺少用量；缺失不代表零消耗，有缺失时以上token不是完整总成本。CLI连接/路由归因依据最后一次失败根轨迹的传输签名，未定位本地代理还是远端服务。",
        f"任务耗时中位数{summary['median_elapsed_seconds']}秒；各任务耗时之和{summary['sum_elapsed_seconds']}秒，不等于并行运行的墙钟耗时。",
        "",
        "100条最终题未运行；40异常仅构造。本轮分母和原始失败不因后续修复改变。成功任务耗时另列，不能用大量提前失败题的整体中位数估算生成速度。",
        "原始日志、完整对话、确认差异、每轮检查和源文件快照保留在本机结果目录。",
    ]
    (destination / f"{len(rows)}题逐题结果.md").write_text(
        "\n".join(lines) + "\n", "utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    report(args.output, args.destination)
