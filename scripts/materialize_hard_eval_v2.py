"""Create and validate an isolated hard-only Agent Core evaluation batch.

The v1 20-case benchmark is historical and intentionally unchanged. This
script creates v2 hard cases under evaluation_sets/codex-cli-v2-hard/ so the
new difficulty batch cannot silently change the v1 denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_sets" / "codex-cli-v2-hard"
SAFE_SELECTOR = re.compile(r"^[#.][A-Za-z][A-Za-z0-9_-]*$")
ALLOWED_ACTIONS = {"click", "fill", "select"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


CASE_DEFS: list[dict[str, Any]] = [
    {
        "id": "hard-invoice-reconciliation-01",
        "name": "三方对账与差异审批台",
        "industry": "财务共享",
        "audience": "财务审核员",
        "intent": "把采购订单、收货记录和发票逐行匹配，并对差异进入审批和审计流程。",
        "goal": "保持订单、行项目、收货数量和发票金额的一致，按差异阈值选择审批或退回。",
        "phases": ["供应商筛选", "订单核对", "收货匹配", "差异标记", "提交复核", "主管审批", "财务复核", "归档"],
        "branch": "金额差异超过阈值时必须升级审批",
        "invalid": "未填写差异原因不能提交",
        "terminal": "已归档",
        "must_haves": ["订单/收货/发票三方明细", "逐行差异和原因", "阈值审批与退回", "完整审计时间线"],
        "tags": ["three-way-match", "threshold", "audit"],
    },
    {
        "id": "hard-access-review-01",
        "name": "季度权限复核台",
        "industry": "身份治理",
        "audience": "安全管理员",
        "intent": "审查员工和应用的权限矩阵，撤销高风险权限并保留双人审批审计。",
        "goal": "保持员工、应用、权限包和审批人关系一致，禁止没有经理确认的高风险权限关闭周期。",
        "phases": ["团队筛选", "人员选择", "权限矩阵", "风险标记", "撤销申请", "经理确认", "例外升级", "周期关闭"],
        "branch": "高风险权限必须经过经理确认或带理由升级例外",
        "invalid": "高风险权限缺少经理确认不能关闭",
        "terminal": "周期已关闭",
        "must_haves": ["员工/应用权限矩阵", "高风险筛选", "撤销与例外分支", "双人确认", "不可篡改审计"],
        "tags": ["access-review", "dual-control", "immutable-audit"],
    },
    {
        "id": "hard-refund-dispute-01",
        "name": "订单退款争议处理台",
        "industry": "电商售后",
        "audience": "售后主管",
        "intent": "按订单行项目处理部分或全额退款，校验金额、时间窗口、证据和审批策略。",
        "goal": "保持订单、商品行、可退金额和退款状态一致，高金额退款必须走双级审批。",
        "phases": ["订单搜索", "商品行选择", "金额填写", "证据选择", "策略校验", "主管审批", "财务审批", "退款执行", "通知关闭"],
        "branch": "超额、过期和高金额退款必须进入不同阻断或审批分支",
        "invalid": "退款金额超过可退金额或时间窗口已过",
        "terminal": "退款已关闭",
        "must_haves": ["订单/行项目选择", "金额上限校验", "证据和原因", "双级审批", "退款审计"],
        "tags": ["refund", "policy-window", "idempotency"],
    },
    {
        "id": "hard-release-gate-01",
        "name": "软件发布门禁台",
        "industry": "研发交付",
        "audience": "发布经理",
        "intent": "把版本变更、依赖、测试、风险、双人审批、金丝雀和回滚串成可审计发布流程。",
        "goal": "只有所有前置门禁和双人审批通过后才能全量发布，金丝雀失败只能回滚。",
        "phases": ["版本选择", "变更查看", "依赖检查", "测试证据", "风险填写", "技术批准", "业务批准", "金丝雀", "全量发布", "审计关闭"],
        "branch": "高风险版本需要技术和业务双签，金丝雀失败只能回滚",
        "invalid": "前置门禁未通过不能批准或全量发布",
        "terminal": "发布已关闭",
        "must_haves": ["变更/依赖/测试门禁", "风险提示", "双角色审批", "金丝雀与回滚", "发布审计"],
        "tags": ["release-gate", "canary", "rollback"],
    },
    {
        "id": "hard-data-pipeline-recovery-01",
        "name": "数据管道故障恢复台",
        "industry": "数据平台",
        "audience": "数据运维",
        "intent": "从异常批次定位受影响分区，执行隔离、部分重跑、质量校验和发布。",
        "goal": "保持 run、分区、质量指标和发布状态一致，未达阈值不得发布且不能重复提交重跑。",
        "phases": ["管道选择", "批次查看", "指标分析", "分区选择", "隔离确认", "重跑审批", "部分重跑", "质量校验", "数据发布"],
        "branch": "部分分区可重跑，质量阈值不达标只能继续修复或放弃",
        "invalid": "质量阈值未达标不能发布",
        "terminal": "批次已发布",
        "must_haves": ["run/分区详情", "质量指标", "影响隔离", "重跑范围", "校验和发布状态"],
        "tags": ["data-pipeline", "partition", "quality-gate"],
    },
    {
        "id": "hard-employee-onboarding-01",
        "name": "员工入职权限编排台",
        "industry": "人力与 IT",
        "audience": "入职协调员",
        "intent": "编排员工资料、设备、培训和系统权限，按角色完成经理与 IT 审批。",
        "goal": "资料缺失时不能激活，权限包必须匹配部门，补件只能重跑缺失节点并保留时间线。",
        "phases": ["员工选择", "资料核对", "设备分配", "培训安排", "权限申请", "经理批准", "IT 激活", "缺件升级", "补件复核", "入职完成"],
        "branch": "缺件进入升级分支，补件后只能重新执行缺失节点",
        "invalid": "资料缺失或权限包不匹配不能激活",
        "terminal": "入职已完成",
        "must_haves": ["资料缺项", "设备/培训任务", "部门权限包", "角色审批", "完整时间线"],
        "tags": ["onboarding", "dependency-graph", "role-approval"],
    },
    {
        "id": "hard-product-recall-01",
        "name": "产品召回处置台",
        "industry": "供应链质量",
        "audience": "质量经理",
        "intent": "从产品批次识别受影响订单，隔离库存并按换货或退款分支追踪客户响应。",
        "goal": "保持批次、订单、客户响应和库存隔离的一致，未确认批次不能通知，关闭后不能修改。",
        "phases": ["批次选择", "仓库筛选", "订单映射", "影响确认", "库存隔离", "处置选择", "通知批准", "响应追踪", "未响应升级", "召回关闭"],
        "branch": "换货和退款互斥，未响应订单必须升级不能直接关闭",
        "invalid": "影响批次未确认不能发送通知",
        "terminal": "召回已关闭",
        "must_haves": ["批次/订单映射", "库存隔离", "换货/退款分支", "响应追踪", "未响应审计"],
        "tags": ["recall", "batch-order-customer", "mutually-exclusive"],
    },
    {
        "id": "hard-budget-control-01",
        "name": "预算偏差控制台",
        "industry": "财务管理",
        "audience": "预算经理",
        "intent": "审查月度预算与实际偏差，发起调账并按金额阈值完成审批和冻结。",
        "goal": "保持月份、成本中心、科目和调账金额一致，小额单级审批、大额双级审批，冻结后拒绝编辑。",
        "phases": ["月份选择", "成本中心", "科目查看", "偏差标记", "原因填写", "调账提交", "主管批准", "财务批准", "冻结审计"],
        "branch": "金额阈值决定单级或双级审批，冻结后只能查看审计",
        "invalid": "缺少偏差原因或审批未完成不能冻结",
        "terminal": "预算已冻结",
        "must_haves": ["预算/实际/偏差表", "阈值提示", "调账表单", "双级审批", "冻结审计"],
        "tags": ["budget", "threshold-approval", "terminal-lock"],
    },
]


def controls(case: dict[str, Any]) -> dict[str, str]:
    return {
        "#filter": "select: filter or scope",
        "#entity": "select: primary entity",
        "#subentity": "select: child record",
        "#reason": "textarea: reason",
        "#phase-1": "button: phase 1",
        "#phase-2": "button: phase 2",
        "#phase-3": "button: phase 3",
        "#phase-4": "button: phase 4",
        "#phase-5": "button: phase 5",
        "#phase-6": "button: phase 6",
        "#phase-7": "button: phase 7",
        "#phase-8": "button: phase 8",
        "#phase-9": "button: phase 9",
        "#phase-10": "button: phase 10",
        "#phase-11": "button: phase 11",
        "#branch": "button: branch action",
        "#approve": "button: approve",
        "#reject": "button: reject",
        "#terminal": "button: terminal action",
        "#reset": "button: reset",
        "#status": "visible current state",
        "#summary": "visible aggregate summary",
        "#timeline": "visible audit timeline",
        "#errors": "visible blocking reason",
    }


def tests(case: dict[str, Any]) -> list[dict[str, Any]]:
    phases = case["phases"]
    happy: list[dict[str, Any]] = [
        {"action": "select", "selector": "#entity", "value": "entity-01", "assertions": {}},
        {"action": "select", "selector": "#subentity", "value": "sub-01", "assertions": {}},
        {"action": "fill", "selector": "#reason", "value": "本轮高难流程核验", "assertions": {}},
    ]
    for index, phase in enumerate(phases, start=1):
        happy.append({
            "action": "click",
            "selector": f"#phase-{index}",
            "value": "",
            "assertions": {"#status": {"contains": [phase], "changed": True}, "#timeline": {"contains": [phase]}},
        })
    happy.extend([
        {"action": "click", "selector": "#terminal", "value": "", "assertions": {"#status": {"contains": [case["terminal"]]}, "#timeline": {"contains": [case["terminal"]]}}},
        {"action": "click", "selector": "#reset", "value": "", "assertions": {"#status": {"contains": ["待处理"]}, "#timeline": {"excludes": [case["terminal"]]}}},
    ])
    invalid = [
        {"action": "select", "selector": "#entity", "value": "entity-02", "assertions": {"#status": {"contains": ["待处理"]}}},
        {"action": "click", "selector": "#terminal", "value": "", "assertions": {"#status": {"contains": ["待处理"]}, "#errors": {"contains": [case["invalid"]]}}},
    ]
    branch = [
        {"action": "select", "selector": "#entity", "value": "entity-01", "assertions": {}},
        {"action": "fill", "selector": "#reason", "value": "触发规则分支", "assertions": {}},
        {"action": "click", "selector": "#branch", "value": "", "assertions": {"#status": {"contains": ["分支处理中"]}, "#timeline": {"contains": ["分支"]}, "#summary": {"contains": [case["branch"][:8]]}}},
        {"action": "click", "selector": "#reject", "value": "", "assertions": {"#status": {"contains": ["已退回"]}, "#errors": {"contains": ["原因"]}}},
    ]
    isolation = [
        {"action": "select", "selector": "#entity", "value": "entity-03", "assertions": {"#status": {"contains": ["待处理"], "excludes": [phases[-1]]}, "#timeline": {"excludes": [phases[0]]}}},
    ]
    return [
        {"id": "happy-path", "steps": happy},
        {"id": "invalid-terminal-action", "steps": invalid},
        {"id": "threshold-or-role-branch", "steps": branch},
        {"id": "entity-isolation", "steps": isolation},
    ]


def materialize() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    case_manifest: list[dict[str, Any]] = []
    for case in CASE_DEFS:
        case_root = OUT / "testdata" / case["id"]
        case_root.mkdir(parents=True, exist_ok=True)
        acceptance = {
            "schema_version": "core-acceptance-v2",
            "case_id": case["id"],
            "difficulty": "hard",
            "intent": case["intent"],
            "goal": case["goal"],
            "flow_steps": case["phases"],
            "expected_result": case["must_haves"] + [case["branch"], case["terminal"]],
            "evaluation_method": ["完成全流程正向路径", "触发非法终态和规则分支", "切换三个实体确认状态和审计隔离", "确认无外部服务调用"],
            "controls": controls(case),
            "tests": tests(case),
            "policy": "Every journey starts from a fresh page; all branch, isolation and terminal assertions must be visible; missing evidence fails.",
            "runner": {"command": f"python scripts/core_acceptance_cli.py --workspace <run-workspace> --case-id {case['id']}", "authoritative_runner": "DemoPilot Core Acceptance Runner", "publish_only_after": "all tests passed and latest source hash matches tested source"},
        }
        inputs = {
            "schema_version": "core-inputs-v2",
            "case_id": case["id"],
            "industry": case["industry"],
            "audience": case["audience"],
            "scenario": case["intent"],
            "fixtures": {"entities": [{"id": "entity-01", "label": "对象一"}, {"id": "entity-02", "label": "对象二"}, {"id": "entity-03", "label": "对象三"}], "subentities": ["sub-01", "sub-02", "sub-03"], "rules": case["branch"], "terminal": case["terminal"]},
            "paths": {"acceptance": f"testdata/{case['id']}/acceptance.json", "inputs": f"testdata/{case['id']}/inputs.json"},
        }
        write_json(case_root / "inputs.json", inputs)
        write_json(case_root / "acceptance.json", acceptance)
        manifest = {"case_id": case["id"], "difficulty": "hard", "files": [{"path": "inputs.json", "sha256": sha256(case_root / "inputs.json")}, {"path": "acceptance.json", "sha256": sha256(case_root / "acceptance.json")}], "status": "authored_not_run"}
        write_json(case_root / "manifest.json", manifest)
        issues: list[str] = []
        for test in acceptance["tests"]:
            for step in test["steps"]:
                if step["action"] not in ALLOWED_ACTIONS or not SAFE_SELECTOR.fullmatch(step["selector"]):
                    issues.append(f"unsafe action/selector in {test['id']}")
                if step["selector"] not in acceptance["controls"]:
                    issues.append(f"undeclared selector {step['selector']}")
                for target, expected in step.get("assertions", {}).items():
                    if not SAFE_SELECTOR.fullmatch(target) or target not in acceptance["controls"] or not isinstance(expected, dict):
                        issues.append(f"invalid assertion {target}")
        status = "passed" if not issues else "failed"
        records.append({"case_id": case["id"], "difficulty": "hard", "flow_count": len(case["phases"]), "test_count": len(acceptance["tests"]), "status": status, "issues": issues})
        case_manifest.append({
            **{key: case[key] for key in ("id", "name", "industry", "audience", "intent", "goal", "phases", "branch", "invalid", "terminal", "must_haves", "tags")},
            "difficulty": "hard",
            "flow_steps": case["phases"],
            "acceptance_criteria": acceptance["expected_result"],
            "evaluation_method": acceptance["evaluation_method"],
            "assets": [],
            "browser_contract": {"fixture": inputs["fixtures"], "controls": acceptance["controls"], "tests": acceptance["tests"], "policy": acceptance["policy"]},
            "complexity": {
                "stage_count": len(case["phases"]),
                "entity_count": 3,
                "child_record_depth": 2,
                "branch_count": 3,
                "negative_paths": 2,
                "approval_roles": 2,
                "derived_aggregates": 1,
                "audit_required": True,
                "terminal_lock": True,
            },
        })
    write_json(OUT / "cases.json", {"schema_version": "codex-cli-hard-v2", "purpose": "Higher-complexity Agent Core cases; separate denominator from v1.", "difficulty_rule": ">=8 phases, >=3 entities or child records, >=2 positive/negative/branch paths, threshold or role/time rule, and audit/isolation assertions.", "cases": case_manifest})
    audit = {"schema_version": "codex-hard-v2-audit", "case_count": len(records), "tier_counts": {"hard": len(records)}, "cases": records, "status": "passed" if all(item["status"] == "passed" for item in records) else "failed", "execution_status": "contracts_authored_not_run"}
    write_json(OUT / "manifest.json", audit)
    (OUT / "README.md").write_text("""# Codex CLI Agent Core hard v2\n\n这是独立于 v1 的高难评测批次，包含 8 个案例。每个案例至少有 8 个连续阶段、3 个实体、正向路径、非法路径、规则分支和实体隔离检查；数据目录为 `testdata/<case-id>/`。\n\n`manifest.json` 的 `status=passed` 只表示 acceptance contract 和 selector 静态审计通过，`execution_status=contracts_authored_not_run` 表示尚未启动真实 Codex CLI。它不能和 v1 的 20-case 结果合并。\n\n建议先用 3 个 v1 hard + 2 个 v2 hard 做小批真实运行，确认 runner 能承受新 contract，再扩展到完整 v2。\n""", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    audit = materialize()
    print(json.dumps({"status": audit["status"], "case_count": audit["case_count"], "execution_status": audit["execution_status"], "output": str(OUT)}, ensure_ascii=False))
    return 0 if audit["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
