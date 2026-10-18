"""Version full business coverage without modifying frozen v1 fixtures."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "evaluation_sets/sales-business-v2"
IDS = ("simple-quote-generator-01", "medium-lead-followup-01", "hard-procurement-approval-01")


def step(action, selector, value="", assertions=None):
    return {"action": action, "selector": selector, "value": value, "assertions": assertions or {}}


def expect(contains=(), excludes=()):
    return {"contains": list(contains), "excludes": list(excludes)}


def build_cases():
    cases = []
    for case_id in IDS:
        original = ROOT / "testdata" / case_id
        inputs = json.loads((original / "inputs.json").read_text(encoding="utf-8"))
        contract = json.loads((original / "acceptance.json").read_text(encoding="utf-8"))
        contract["tests"] = []
        contract["coverage_revision"] = "sales-business-v2"
        if case_id == IDS[0]:
            contract["controls"]["#breakdown"] = "visible breakdown with labels 小计 and 折扣"
            for index, (plan, price) in enumerate(inputs["fixtures"]["prices_per_seat"].items()):
                for seats in (1, 3, 4, 7):
                    contract["tests"].append({"id": f"plan-{index}-seats-{seats}", "steps": [
                        step("select", "#plan", plan), step("fill", "#seats", str(seats)),
                        step("click", "#calculate", assertions={"#total": expect([str(price * seats)])})]})
            contract["tests"].append({"id": "subtotal-discount", "steps": [step("click", "#calculate", assertions={"#breakdown": expect(["小计", "折扣"])})]})
            contract["expected_result"] += ["小计和折扣明细可见；覆盖两套餐与四种席位数量"]
        elif case_id == IDS[1]:
            inputs["fixtures"]["task_list_scope"] = "global: existing follow-ups remain visible with original lead ID/name/owner after switching the current lead"
            contract["goal"] += "；跟进列表为全局历史，切换线索不隐藏或改标已创建的记录。"
            leads = inputs["fixtures"]["leads"]
            for index, lead in enumerate(leads):
                other = leads[(index + 1) % len(leads)]
                for owner_index, owner in enumerate(inputs["fixtures"]["owners"]):
                    contract["tests"].append({"id": f"lead-{index}-owner-{owner_index}", "steps": [
                        step("select", "#industry", lead["industry"], {"#list": expect([lead["name"]], [other["name"]])}),
                        step("select", "#lead", lead["id"], {"#detail": expect([lead["name"]])}),
                        step("select", "#owner", owner),
                        step("click", "#create", assertions={"#tasks": expect([lead["id"], owner, "待跟进"])}),
                        step("select", "#industry", other["industry"]),
                        step("select", "#lead", other["id"], {"#detail": expect([other["name"]], [lead["name"]]), "#tasks": expect([lead["id"], owner], [other["id"]])})]})
            contract["expected_result"] += ["覆盖全部线索/负责人组合；全局跟进历史保持原来归属"]
        else:
            fixture = inputs["fixtures"]
            fixture["suppliers"] = [{"id": letter, "name": f"供应商 {letter}", "quote": price, "delivery_days": days} for letter, price, days in (("A", 100, 5), ("B", 110, 3), ("C", 95, 7))]
            fixture["comparison_ui"] = "Visible table #suppliers with one row per supplier; native #supplier select labels 供应商 A/供应商 B/供应商 C; show chosen name in #status or #timeline."
            fixture["validation_ui"] = "Keep transition buttons enabled and show rejection messages. Rejection after submission is 已退回 with reason. Only approved requests may order/receive. Reset clears all entities."
            contract["controls"].update({"#supplier": "select: 供应商 A/供应商 B/供应商 C", "#suppliers": "visible comparison table with one row per supplier"})
            entities, owners, transitions = fixture["entities"], fixture["owners"], fixture["ordered_transitions"]
            initial, terminal = fixture["initial_state"], transitions[-1][1]
            for index, entity in enumerate(entities):
                other = entities[(index + 1) % len(entities)]
                for owner_index, owner in enumerate(owners):
                    reason = "独立验收：采购演示理由"
                    steps = [step("select", "#entity", entity["id"]), step("select", "#owner", owner), step("fill", "#reason", reason)]
                    visited = []
                    for action, state in transitions:
                        visited.append(state)
                        steps.append(step("click", f"#{action}", assertions={"#status": expect([entity["id"], owner, state]), "#timeline": expect([*visited, owner])}))
                    steps += [
                        step("click", "#illegal", assertions={"#status": expect([terminal]), "#errors": expect(["不可回退"])}),
                        step("select", "#entity", other["id"], {"#status": expect([other["id"], initial], [terminal]), "#timeline": expect([], [*visited, reason])}),
                        step("click", "#reset")]
                    for reset_entity in entities:
                        steps.append(step("select", "#entity", reset_entity["id"], {"#status": expect([initial], [terminal]), "#timeline": expect([], [*visited, reason])}))
                    contract["tests"].append({"id": f"entity-{index}-owner-{owner_index}-main", "steps": steps})
                contract["tests"].append({"id": f"entity-{index}-out-of-order", "steps": [
                    step("select", "#entity", entity["id"]), step("click", "#receive", assertions={"#status": expect([initial], [terminal]), "#errors": expect(["前置步骤未完成"])})]})
                contract["tests"].append({"id": f"entity-{index}-missing-reason", "steps": [
                    step("select", "#entity", entity["id"]), step("select", "#owner", owners[0]), step("fill", "#reason", ""),
                    step("click", "#create-request", assertions={"#status": expect([initial], [transitions[0][1]]), "#errors": expect(["理由"])})]})
                reason, owner = "独立验收：预算需要复核", owners[index % len(owners)]
                reject = [step("select", "#entity", entity["id"]), step("select", "#owner", owner), step("fill", "#reason", reason)]
                reject += [step("click", f"#{action}") for action, _ in transitions[:4]]
                reject.append(step("click", "#reject", assertions={"#status": expect(["已退回", reason], ["已批准"]), "#timeline": expect(["已退回", owner, reason])}))
                contract["tests"].append({"id": f"entity-{index}-reject", "steps": reject})
            contract["tests"].append({"id": "three-suppliers-and-chosen-B", "steps": [
                step("select", "#owner", owners[0]), step("fill", "#reason", "比较供应商"), step("click", "#create-request"),
                step("click", "#compare", assertions={"#suppliers": expect(["供应商 A", "供应商 B", "供应商 C", "100", "110", "95"])}),
                step("select", "#supplier", "供应商 B"), step("click", "#choose", assertions={"#status": expect(["方案已选", "供应商 B"])})]})
            contract["goal"] += "；比较指定三家供应商的报价和交期，并可观察所选名称；覆盖全部申请与负责人，重置清除所有记录。"
            contract["expected_result"] += ["三家供应商与所选名称可见；全部申请/负责人、乱序、缺理由、拒绝、终态锁和重置均正确"]
        cases.append({"id": case_id, "inputs": inputs, "contract": contract})
    return cases


def main():
    cases = build_cases()
    for case in cases:
        directory = DEST / "testdata" / case["id"]
        if directory.exists():
            raise SystemExit(f"Refusing to overwrite versioned fixtures: {directory}")
        directory.mkdir(parents=True)
        files = []
        for name, value in (("inputs.json", case["inputs"]), ("acceptance.json", case["contract"])):
            payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
            (directory / name).write_bytes(payload)
            files.append({"path": name, "sha256": hashlib.sha256(payload).hexdigest()})
        (directory / "manifest.json").write_text(json.dumps({"case_id": case["id"], "files": files}, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(cases), "journeys": sum(len(case["contract"]["tests"]) for case in cases), "old_fixtures_modified": False}))


if __name__ == "__main__":
    main()
