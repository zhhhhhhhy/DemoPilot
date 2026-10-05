"""Materialize authored data and browser contracts for the development set."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evaluation_sets/codex-cli-v1"


def action(action: str, selector: str, value: str = "", **assertions):
    return {"action": action, "selector": selector, "value": value, "assertions": assertions}


def contract(controls: dict, tests: list, fixture: dict, *, notes: str = ""):
    return {
        "fixture": fixture,
        "controls": controls,
        "tests": tests,
        "notes": notes,
        "policy": "All test assertions refer to visible UI. Reset page for each independent journey; missing evidence is a failure.",
    }


def test(name: str, steps: list):
    return {"id": name, "steps": steps}


def main():
    specs = {}
    specs["simple-invoice-ocr-01"] = contract(
        {"#invoice-select": "select: invoice-01 through invoice-10", "#recognize": "button: 识别", "#status": "visible status", "#fields": "visible extracted fields"},
        [test("two-distinct-images", [
            action("select", "#invoice-select", "invoice-01"),
            action("click", "#recognize", **{"#status": {"contains": ["识别完成"], "changed": True}, "#fields": {"contains": ["供应方", "发票号"], "changed": True}}),
            action("select", "#invoice-select", "invoice-02"),
            action("click", "#recognize", **{"#status": {"contains": ["识别完成"], "changed": True}, "#fields": {"contains": ["供应方", "发票号"], "changed": True}}),
        ])],
        {"image_ids": [f"invoice-{i:02d}" for i in range(1, 11)], "processing_mode": "local static OCR demonstration; no external OCR engine"},
        notes="Use attached invoice pictures to prepare the display-only extraction data. Reference labels are excluded from the model prompt. Assertions only measure visible completion and input switching, not OCR-model accuracy; invoice-gold.json remains held out for a separate extraction benchmark.",
    )
    specs["simple-receipt-summary-01"] = contract(
        {"#receipt-select": "select: R-01/R-02", "#summary": "visible summary"},
        [test("switch-receipt", [action("select", "#receipt-select", "R-02", **{"#summary": {"contains": ["北岸咖啡", "38"], "excludes": ["86"]}})])],
        {"receipts": [{"id": "R-01", "merchant": "晨光书店", "date": "2026-09-01", "total": 86}, {"id": "R-02", "merchant": "北岸咖啡", "date": "2026-09-02", "total": 38}]},
    )
    specs["simple-appointment-card-01"] = contract(
        {"#date": "input type=date", "#time": "select: 09:00/14:30", "#confirm": "button", "#status": "visible error or confirmation"},
        [test("required-fields", [action("click", "#confirm", **{"#status": {"contains": ["请选择日期"], "excludes": ["预约成功"]}})]), test("valid-appointment", [action("fill", "#date", "2026-11-12"), action("select", "#time", "14:30"), action("click", "#confirm", **{"#status": {"contains": ["预约成功", "2026-11-12", "14:30"], "changed": True}})])],
        {"times": ["09:00", "14:30"], "default_date": "", "default_time": ""},
    )
    specs["simple-sku-lookup-01"] = contract(
        {"#sku": "input", "#lookup": "button", "#result": "visible product or error"},
        [test("known-and-unknown", [action("fill", "#sku", "SKU-002"), action("click", "#lookup", **{"#result": {"contains": ["蓝牙键盘", "24", "B-02"]}}), action("fill", "#sku", "BAD-999"), action("click", "#lookup", **{"#result": {"contains": ["未找到"], "excludes": ["蓝牙键盘"]}})])],
        {"products": [{"sku": "SKU-001", "name": "无线鼠标", "stock": 12, "location": "A-01"}, {"sku": "SKU-002", "name": "蓝牙键盘", "stock": 24, "location": "B-02"}]},
    )
    specs["simple-expense-entry-01"] = contract(
        {"#amount": "input number", "#category": "select: 交通/住宿", "#save": "button", "#status": "visible status", "#records": "visible saved rows", "#total": "visible sum"},
        [test("reject-empty", [action("click", "#save", **{"#status": {"contains": ["请输入有效金额"]}})]), test("two-amounts", [action("fill", "#amount", "128.50"), action("select", "#category", "交通"), action("click", "#save", **{"#records": {"contains": ["128.50", "交通"]}, "#total": {"contains": ["128.50"]}}), action("fill", "#amount", "71.50"), action("select", "#category", "住宿"), action("click", "#save", **{"#total": {"contains": ["200.00"]}})])],
        {"initial_records": [], "categories": ["交通", "住宿"]},
    )
    specs["simple-feedback-tag-01"] = contract(
        {"#feedback": "textarea", "#analyze": "button", "#result": "visible topic and sentiment"},
        [test("opposite-sentiments", [action("fill", "#feedback", "配送太慢，我很失望"), action("click", "#analyze", **{"#result": {"contains": ["物流", "负向"]}}), action("fill", "#feedback", "客服很热心，我很满意"), action("click", "#analyze", **{"#result": {"contains": ["服务", "正向"], "excludes": ["负向"]}})])],
        {"rules": [{"topic_keyword": "配送", "topic": "物流"}, {"topic_keyword": "客服", "topic": "服务"}], "positive_keywords": ["满意", "热心"], "negative_keywords": ["失望", "太慢"], "mode": "local rules demo"},
    )
    specs["simple-shipment-status-01"] = contract(
        {"#shipment": "input", "#query": "button", "#result": "visible status and ETA"},
        [test("found-then-missing", [action("fill", "#shipment", "SHIP-002"), action("click", "#query", **{"#result": {"contains": ["派送中", "2026-11-03"]}}), action("fill", "#shipment", "UNKNOWN"), action("click", "#query", **{"#result": {"contains": ["未找到"], "excludes": ["派送中"]}})])],
        {"shipments": [{"id": "SHIP-001", "node": "已揽收", "eta": "2026-11-05"}, {"id": "SHIP-002", "node": "派送中", "eta": "2026-11-03"}]},
    )
    specs["simple-profile-completion-01"] = contract(
        {"#name": "input", "#department": "input", "#contact": "input", "#check": "button", "#progress": "visible percentage", "#status": "visible status"},
        [test("partial-to-complete", [action("fill", "#name", "演示员工"), action("click", "#check", **{"#progress": {"contains": ["33"]}, "#status": {"contains": ["未完成"]}}), action("fill", "#department", "产品部"), action("fill", "#contact", "demo@example.invalid"), action("click", "#check", **{"#progress": {"contains": ["100%"]}, "#status": {"contains": ["已完成"]}})])],
        {"required_fields": ["name", "department", "contact"], "initial_fields": {"name": "", "department": "", "contact": ""}},
    )
    specs["simple-quote-generator-01"] = contract(
        {"#plan": "select: 基础/专业", "#seats": "input number", "#calculate": "button", "#total": "visible quote"},
        [test("dependent-pricing", [action("select", "#plan", "专业"), action("fill", "#seats", "3"), action("click", "#calculate", **{"#total": {"contains": ["600"]}}), action("fill", "#seats", "4"), action("click", "#calculate", **{"#total": {"contains": ["800"], "excludes": ["600"]}})])],
        {"prices_per_seat": {"基础": 100, "专业": 200}, "discount": 0, "formula": "price_per_seat * seats", "boundary": "演示估算"},
    )
    specs["simple-faq-answer-01"] = contract(
        {"#question": "select: FAQ-01/FAQ-02/FAQ-03", "#answer": "visible answer and source"},
        [test("answer-switch", [action("select", "#question", "FAQ-02", **{"#answer": {"contains": ["每周五", "员工手册"], "excludes": ["三天"]}}), action("select", "#question", "FAQ-03", **{"#answer": {"contains": ["工单", "IT 指南"], "excludes": ["每周五"]}})])],
        {"faqs": [{"id": "FAQ-01", "question": "请假需要提前多久？", "answer": "提前三天申请。", "source": "员工手册"}, {"id": "FAQ-02", "question": "费用什么时候报销？", "answer": "每周五集中处理。", "source": "员工手册"}, {"id": "FAQ-03", "question": "电脑故障如何处理？", "answer": "提交 IT 工单。", "source": "IT 指南"}], "updated": "2026-09-01"},
    )
    specs["medium-invoice-review-01"] = contract(
        {"#invoice-select": "select: invoice-01/invoice-02/invoice-03", "#fields": "visible fields", "#note": "textarea", "#approve": "button 已复核", "#return": "button 需补充", "#status": "visible per-invoice status"},
        [test("per-invoice-state", [action("select", "#invoice-select", "invoice-01"), action("click", "#approve", **{"#status": {"contains": ["invoice-01", "已复核"]}}), action("select", "#invoice-select", "invoice-02", **{"#status": {"contains": ["待复核"], "excludes": ["已复核"]}}), action("click", "#return", **{"#status": {"contains": ["请填写原因"]}}), action("fill", "#note", "请补充采购编号"), action("click", "#return", **{"#status": {"contains": ["invoice-02", "需补充", "采购编号"]}}), action("select", "#invoice-select", "invoice-01", **{"#status": {"contains": ["已复核"], "excludes": ["需补充"]}})])],
        {"invoice_ids": ["invoice-01", "invoice-02", "invoice-03"], "initial_status": "待复核"}, notes="Selected images are attached. This tests review-state isolation; OCR accuracy is not scored.",
    )
    specs["medium-lead-followup-01"] = contract(
        {"#industry": "select: 全部/制造/零售", "#lead": "select: L-01/L-02", "#list": "visible filtered list", "#detail": "visible lead detail", "#owner": "select: 林澄/周岚", "#create": "button", "#tasks": "visible tasks"},
        [test("filter-to-task", [action("select", "#industry", "制造", **{"#list": {"contains": ["星港制造"], "excludes": ["云帆零售"]}}), action("select", "#lead", "L-01", **{"#detail": {"contains": ["星港制造"]}}), action("select", "#owner", "林澄"), action("click", "#create", **{"#tasks": {"contains": ["L-01", "林澄", "待跟进"]}})])],
        {"leads": [{"id": "L-01", "name": "星港制造", "industry": "制造"}, {"id": "L-02", "name": "云帆零售", "industry": "零售"}], "owners": ["林澄", "周岚"], "initial_tasks": []},
    )
    specs["medium-replenishment-01"] = contract(
        {"#stock-filter": "select: 全部/低库存", "#sku": "select: SKU-001/SKU-002", "#list": "visible filtered list", "#detail": "visible SKU details", "#quantity": "input number", "#create": "button", "#tasks": "visible tasks"},
        [test("low-stock-task", [action("select", "#stock-filter", "低库存", **{"#list": {"contains": ["无线鼠标"], "excludes": ["蓝牙键盘"]}}), action("select", "#sku", "SKU-001", **{"#detail": {"contains": ["无线鼠标", "8"]}}), action("fill", "#quantity", "32"), action("click", "#create", **{"#tasks": {"contains": ["SKU-001", "32", "待处理"]}})])],
        {"products": [{"sku": "SKU-001", "name": "无线鼠标", "stock": 8}, {"sku": "SKU-002", "name": "蓝牙键盘", "stock": 80}], "low_stock_below": 20, "initial_tasks": []},
    )
    specs["medium-support-triage-01"] = contract(
        {"#priority-filter": "select: 全部/高", "#ticket": "select: TK-01/TK-02", "#list": "visible filtered list", "#detail": "visible detail", "#priority": "select: 高/中/低", "#note": "textarea", "#save": "button", "#status": "visible saved status"},
        [test("triage-sync", [action("select", "#priority-filter", "高", **{"#list": {"contains": ["无法登录"], "excludes": ["修改昵称"]}}), action("select", "#ticket", "TK-01"), action("select", "#priority", "中"), action("fill", "#note", "已提供临时解决方案"), action("click", "#save", **{"#status": {"contains": ["TK-01", "中", "临时解决方案"]}, "#list": {"excludes": ["无法登录"]}})])],
        {"tickets": [{"id": "TK-01", "subject": "无法登录", "priority": "高"}, {"id": "TK-02", "subject": "修改昵称", "priority": "低"}]},
    )
    specs["medium-content-calendar-01"] = contract(
        {"#campaign": "select: 春季发布/新品首发", "#copy": "textarea", "#preview-button": "button", "#preview": "visible preview", "#schedule": "button", "#status": "visible queue or error"},
        [test("empty-copy", [action("click", "#schedule", **{"#status": {"contains": ["请填写文案"]}})]), test("draft-to-queue", [action("select", "#campaign", "新品首发"), action("fill", "#copy", "今天发布轻量协同工具"), action("click", "#preview-button", **{"#preview": {"contains": ["新品首发", "轻量协同工具"]}}), action("click", "#schedule", **{"#status": {"contains": ["待发布", "新品首发", "轻量协同工具"]}})])],
        {"campaigns": ["春季发布", "新品首发"], "initial_queue": []},
    )
    hard = [
        ("hard-procurement-approval-01", "采购申请", "P-01", ["需求已创建", "已比较", "方案已选", "待审批", "已批准", "订单已下达", "已验收"], ["create-request", "compare", "choose", "submit", "approve", "order", "receive"]),
        ("hard-incident-response-01", "安全事件", "INC-01", ["已分级", "已分派", "已隔离", "调查中", "已修复", "已复验", "已关闭"], ["triage", "assign", "isolate", "investigate", "resolve", "verify", "close"]),
        ("hard-contract-renewal-01", "续签合同", "C-01", ["已识别到期", "已比较条款", "已复核", "方案已编辑", "待审批", "已批准", "已生效"], ["find", "compare", "review", "edit", "submit", "approve", "activate"]),
        ("hard-logistics-exception-01", "延误订单", "O-01", ["异常已定位", "原因已确认", "任务已创建", "已改派", "已重排", "已通知", "已关闭"], ["filter", "inspect", "create", "reassign", "reschedule", "notify", "close"]),
        ("hard-clinic-followup-01", "随访计划", "F-01", ["风险已分层", "计划已创建", "已分派", "已安排", "随访已记录", "已复核", "已闭环"], ["risk", "plan", "assign", "schedule", "record", "review", "close"]),
    ]
    for case_id, entity, entity_id, states, buttons in hard:
        controls = {f"#{b}": "button: execute the named business transition" for b in buttons}
        controls.update({"#entity": f"select: {entity_id}/{entity_id[:-1]}2", "#owner": "select: 林澄/周岚", "#reason": "textarea", "#status": "visible current entity, owner, state and reason", "#timeline": "visible per-entity audit", "#reject": "button: return request to start with reason", "#illegal": "button: illegal rollback after terminal state", "#reset": "button: reset all entities", "#errors": "visible rejection reason"})
        steps = [action("select", "#entity", entity_id), action("select", "#owner", "林澄"), action("fill", "#reason", "本轮演示核验")]
        steps += [action("click", f"#{b}", **{"#status": {"contains": [entity_id, "林澄", state], "changed": True}, "#timeline": {"contains": [state]}}) for state, b in zip(states, buttons, strict=True)]
        steps += [action("click", "#illegal", **{"#status": {"contains": [states[-1]]}, "#errors": {"contains": ["不可回退"]}}), action("select", "#entity", entity_id[:-1]+"2", **{"#status": {"contains": ["待处理"], "excludes": [states[-1]]}}), action("click", "#reset", **{"#timeline": {"excludes": [states[-1]]}})]
        invalid = [action("click", "#"+buttons[-1], **{"#status": {"contains": ["待处理"]}, "#errors": {"contains": ["前置步骤未完成"]}})]
        branch = [action("select", "#owner", "周岚"), action("fill", "#reason", "资料需要补充"), action("click", "#"+buttons[0]), action("click", "#reject", **{"#status": {"contains": ["已退回", "资料需要补充"]}, "#timeline": {"contains": ["已退回", "周岚"]}})]
        if "clinic" in case_id:
            controls["#overdue"] = "button: simulate overdue for current follow-up"
            controls["#escalate"] = "button: escalate overdue task"
            branch = [action("select", "#owner", "周岚"), action("fill", "#reason", "逾期未联系"), action("click", "#"+buttons[0]), action("click", "#overdue", **{"#status": {"contains": ["已逾期"]}}), action("click", "#escalate", **{"#status": {"contains": ["已升级", "周岚"]}, "#timeline": {"contains": ["已逾期", "已升级"]}})]
        specs[case_id] = contract(controls, [test("main-state-machine", steps), test("out-of-order-blocked", invalid), test("return-or-escalate", branch)], {"entity_type": entity, "entities": [{"id": entity_id, "title": entity+"甲"}, {"id": entity_id[:-1]+"2", "title": entity+"乙"}], "owners": ["林澄", "周岚"], "initial_state": "待处理", "ordered_transitions": list(zip(buttons, states, strict=True)), "validation": "Owner and reason required before first transition. Ordinary transitions must follow the order; terminal state rejects rollback; state and history are isolated by entity."}, notes="Show domain context and consequences for each step, not just a list of buttons. Preserve all prior audit events; reset returns to initial state. Negative and branch paths are independent tests.")
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    for case in cases["cases"]:
        case["browser_contract"] = specs[case["id"]]
        if case["difficulty"] == "hard":
            case["flow_steps"] = [text for _, text in specs[case["id"]]["fixture"]["ordered_transitions"]]
    cases["difficulty_rule"] = {"simple": "1-2 个业务处理阶段；输入、选择素材不另算难度。", "medium": "3-5 个业务操作阶段，有筛选、详情及状态联动。", "hard": "6 个以上连续业务处理阶段，同时包含分支、错误阻断、跨实体状态隔离和审计。"}
    cases["protocol"] = {"version": "core-generation-v1", "mode": "core_generation", "planning_owner": "benchmark author", "model_stages": ["builder", "reviewer:final"], "max_revisions": 2, "no_mock_fallback": True, "split": "open development/calibration suite; not a sealed holdout", "hard_pass": "real CLI code + static gates + all frozen browser paths + reviewer pass; preserve all failures in denominator"}
    (ROOT / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Authored {len(specs)} frozen browser contracts")


if __name__ == "__main__":
    main()
