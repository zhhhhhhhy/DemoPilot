"""Create source-derived quotation tasks without overwriting prior evidence.

Public documentation supplies rule families. All product records, thresholds,
dates and seller preferences below are synthetic benchmark configurations.
Neither these preferences nor final expected values are mounted into Core.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation_sets" / "quotation-intent-v1"
PRICE_DOC = "https://docs.frappe.io/erpnext/pricing-rule"
DISCOUNT_DOC = "https://docs.frappe.io/erpnext/applying-discount"
TAX_DOC = "https://docs.frappe.io/erpnext/tax-inclusive-accounting"
FREE_DOC = "https://docs.frappe.io/erpnext/setting-up-buy-1-get-1-free-pricing-rule"

COMMON_BRIEF = "只用给定商品和客户样例做本地离线演示，金额用人民币，未提到的额外优惠或税不添加，页面样式自行决定。"
COMMON_FACTS = (
    "商品和客户原始样例稍后由本地testdata提供，不需向销售索要文件。"
    "两行商品合并报价，第二行数量可为0；不适用的优惠为0，除了明确说明的税之外不另加税。"
    "所有按数量门槛命中的折扣适用于该商品全部付费数量，不做分段计费。"
    "金额先整单汇总再保留两位小数，四舍五入；数量必须是整数，第一行至少1，第二行至少0；"
    "重复计算只重算当前报价，不累计历史优惠；没有真实支付或下单。"
)


def vector(id, product="A", quantity=1, second_product="B", second_quantity=0,
           customer="standard", date="2026-03-15"):
    return dict(id=id, product=product, quantity=quantity,
                second_product=second_product, second_quantity=second_quantity,
                customer=customer, date=date)


def definitions():
    # Split membership is specified before any generation; no adaptive selection.
    return [
        dict(id="quotation-01", split="development", family="quantity_tiers",
             title="按数量门槛分档优惠", source_urls=[PRICE_DOC],
             brief="我是销售，帮我做一个可切换商品和数量、按购买量阶梯优惠的报价演示。",
             policy="只对A商品按该商品合计数量分档：少于5件不打折，5到9件九折，10件及以上八折；B和C不优惠。",
             rules=dict(kind="quantity_tiers", product="A",
                        tiers=[dict(minimum=5, percent="10"), dict(minimum=10, percent="20")]),
             vectors=[vector("below"), vector("just-below", quantity=4),
                      vector("lower-bound", quantity=5), vector("upper-band", quantity=9),
                      vector("next-bound", quantity=10), vector("above", quantity=11),
                      vector("ineligible", product="B", quantity=10)]),
        dict(id="quotation-02", split="development", family="customer_scope",
             title="不同客户享受不同商品折扣", source_urls=[PRICE_DOC],
             brief="我是销售，帮我做一个切换客户后，能按客户优惠重新算价的报价演示。",
             policy="VIP客户购买A商品优惠15%，合作客户购买A商品优惠5%，普通客户不优惠；B和C对所有客户均不优惠。",
             rules=dict(kind="customer_scope", product="A", discounts=dict(vip="15", partner="5")),
             vectors=[vector("standard"), vector("vip", customer="vip"),
                      vector("partner", customer="partner", quantity=3),
                      vector("vip-b", product="B", quantity=2, customer="vip"),
                      vector("vip-two-lines", customer="vip", quantity=2, second_quantity=2),
                      vector("return-standard", quantity=3)]),
        dict(id="quotation-03", split="development", family="validity_dates",
             title="优惠有效期及日期边界", source_urls=[PRICE_DOC],
             initial_information="sufficient",
             brief="我是销售，帮我做一个改日期检查活动价的报价演示：A商品在2026年3月1日至31日优惠25%，包含起止当天，其他日期及商品用原价。",
             policy="A商品仅在2026年3月1日至3月31日享受25%优惠，起止当天都包含；其他日期及B、C均按原价。",
             rules=dict(kind="validity_dates", product="A", start="2026-03-01",
                        end="2026-03-31", percent="25"),
             vectors=[vector("before", date="2026-02-28"),
                      vector("start", date="2026-03-01"),
                      vector("during", quantity=2), vector("end", date="2026-03-31"),
                      vector("after", date="2026-04-01"),
                      vector("ineligible", product="B", date="2026-03-15")]),
        dict(id="quotation-04", split="development", family="compound_discounts",
             title="两项优惠按折后金额连续计算", source_urls=[PRICE_DOC],
             brief="我是销售，帮我做一个能解释两项优惠叠加后实际报价的演示。",
             policy="所有商品先优惠10%，再对第一次优惠后的金额优惠20%；不能把两项优惠相加成30%。展示原金额、优惠总金额和最终金额。",
             rules=dict(kind="compound_discounts", percents=["10", "20"]),
             vectors=[vector("one-a"), vector("three-a", quantity=3),
                      vector("one-b", product="B"), vector("mixed", quantity=2, second_quantity=3),
                      vector("one-c", product="C")]),
        dict(id="quotation-05", split="heldout", family="overlap_priority",
             title="重叠规则采用指定优先级", source_urls=[PRICE_DOC],
             brief="我是销售，帮我做一个客户优惠和批量优惠同时命中时能处理冲突的报价演示。",
             policy="只对A商品：VIP客户优惠10%；数量达到5件的批量优惠是20%。同时命中时VIP规则优先，只用10%，不叠加、不自动选更大优惠；B、C不优惠。",
             rules=dict(kind="overlap_priority", product="A", vip_percent="10",
                        volume_minimum=5, volume_percent="20", priority="vip"),
             vectors=[vector("none"), vector("volume-edge", quantity=5),
                      vector("vip", customer="vip"), vector("overlap", quantity=6, customer="vip"),
                      vector("other-customer", quantity=6, customer="partner"),
                      vector("other-item", product="B", quantity=6, customer="vip"),
                      vector("below-volume", quantity=4)]),
        dict(id="quotation-06", split="heldout", family="mixed_threshold",
             title="跨商品合并数量达到优惠门槛", source_urls=[PRICE_DOC],
             brief="我是销售，帮我做一个把多种商品放进同一报价、合并数量判断优惠的演示。",
             policy="A和B属于同一优惠组，合计购买数量达到5件时，组内两种商品都优惠10%；C不参与凑数，也不享受优惠。",
             rules=dict(kind="mixed_threshold", products=["A", "B"], minimum=5, percent="10"),
             vectors=[vector("below", quantity=2, second_quantity=2),
                      vector("combined-edge", quantity=3, second_quantity=2),
                      vector("single-edge", quantity=5),
                      vector("c-excluded", quantity=3, second_product="C", second_quantity=2),
                      vector("b-first", product="B", quantity=4, second_product="A", second_quantity=1),
                      vector("duplicate-a", quantity=2, second_product="A", second_quantity=3),
                      vector("above", quantity=4, second_quantity=4)]),
        dict(id="quotation-07", split="heldout", family="rate_override",
             title="客户协议单价覆盖目录价", source_urls=[PRICE_DOC],
             initial_information="sufficient",
             brief="我是销售，帮我做一个协议价报价演示：合作客户买A用88元单价替代目录价，其他客户和商品用目录价，展示目录原金额、协议价差额和应付金额。",
             policy="合作客户购买A商品时，以协议单价88元替代目录单价；这不是减88元，也不是打88折。其他客户和商品按目录原价；不额外叠加优惠。页面保留目录原金额，协议价差额计入价格调整金额。",
             rules=dict(kind="rate_override", product="A", customer="partner", rate="88"),
             vectors=[vector("standard"), vector("partner", customer="partner"),
                      vector("partner-multiple", customer="partner", quantity=3),
                      vector("vip", customer="vip"),
                      vector("other-product", product="B", customer="partner", quantity=3),
                      vector("mixed", customer="partner", quantity=2, second_quantity=2)]),
        dict(id="quotation-08", split="heldout", family="tax_inclusive",
             title="含税价反算未税金额和税额", source_urls=[TAX_DOC],
             brief="我是销售，帮我做一个把报价的未税金额、税额和最终应付金额分别显示的演示。",
             policy="给定目录单价均为含税价，内含10%的演示税。未税金额=含税金额除以1.10，税额是两者差额；最终应付就是原含税金额，不能再加一次税。没有折扣。",
             rules=dict(kind="tax_inclusive", tax_percent="10"), prices=dict(A="110", B="66", C="220"),
             vectors=[vector("a-one"), vector("a-three", quantity=3),
                      vector("b-two", product="B", quantity=2),
                      vector("mixed", quantity=2, second_quantity=3),
                      vector("c-one", product="C")]),
        dict(id="quotation-09", split="heldout", family="net_total_discount",
             title="未税金额减固定优惠后重新计算税额", source_urls=[DISCOUNT_DOC],
             brief="我是销售，帮我做一个带整单固定优惠、同时展示税额和最终金额的报价演示。",
             policy="目录价是不含税单价。每张报价先从整单未税金额减30元，最多减到0；然后对折后未税金额计算10%的演示税。优惠不是从含税总价直接减30元。",
             rules=dict(kind="net_total_discount", amount="30", tax_percent="10"),
             vectors=[vector("a-one"), vector("a-two", quantity=2),
                      vector("b-one", product="B"),
                      vector("mixed", quantity=1, second_quantity=2),
                      vector("duplicate", quantity=1, second_product="A", second_quantity=2),
                      vector("c-one", product="C")]),
        dict(id="quotation-10", split="heldout", family="free_items",
             title="买赠数量与收费商品分开计算", source_urls=[FREE_DOC, PRICE_DOC],
             brief="我是销售，帮我做一个买赠报价演示，让客户看到收费数量、免费数量和应付金额。",
             policy="A商品每购买2件付费商品，额外赠送1件A，赠送数向下取整，可重复；例如购买4件付费商品额外送2件。付费数量不包含赠品，赠品单价0；B、C不参与，报价总额仍按付费商品计算。",
             rules=dict(kind="free_items", product="A", buy=2, free=1),
             vectors=[vector("below"), vector("edge", quantity=2),
                      vector("remainder", quantity=3), vector("repeat", quantity=4),
                      vector("ineligible", product="B", quantity=4),
                      vector("mixed", quantity=3, second_quantity=2),
                      vector("duplicate", quantity=1, second_product="A", second_quantity=3)]),
    ]


def engineering_contract(case_id):
    controls = {
        "#product": "native select; option values A, B, C",
        "#quantity": "number input; first paid quantity, integer >=1",
        "#second-product": "native select; option values A, B, C",
        "#second-quantity": "number input; second paid quantity, integer >=0",
        "#customer": "native select; option values standard, vip, partner",
        "#quote-date": "date input; YYYY-MM-DD",
        "#calculate": "button; recalculate without accumulating prior calculations",
        "#subtotal": "visible original catalogue amount before price adjustments; for tax-inclusive prices show the extracted original net amount; only one monetary number",
        "#discount": "visible total monetary price adjustment, including negotiated-rate difference and discounts; only one monetary number",
        "#tax": "visible tax amount; only one monetary number",
        "#total": "visible final payable amount; include CNY and only one monetary number",
        "#free-quantity": "visible number of additional free units; one integer, zero when none",
        "#rule": "visible explanation of selected pricing behavior",
        "#validation": "empty after valid calculation; show a visible error mentioning 数量 for invalid quantity, preserve the last valid quote outputs and clear error after recovery",
    }
    return dict(
        schema_version="core-acceptance-v2", case_id=case_id,
        intent="Implement the supplied sales request using the supplied catalogue.",
        goal="A usable local quotation demo with stable observable controls.",
        expected_result=["All documented controls are operable", "CNY total changes with quantity",
                         "Invalid first quantity is rejected", "No production connection"],
        controls=controls,
        tests=[
            dict(id="operable-quotation", steps=[
                dict(action="select", selector="#product", value="A"),
                dict(action="fill", selector="#quantity", value="1"),
                dict(action="fill", selector="#second-quantity", value="0"),
                dict(action="select", selector="#customer", value="standard"),
                dict(action="fill", selector="#quote-date", value="2026-03-15"),
                dict(action="click", selector="#calculate", value="",
                     assertions={"#total": {"contains": ["CNY"]}}),
                dict(action="fill", selector="#quantity", value="2"),
                dict(action="click", selector="#calculate", value="",
                     assertions={"#total": {"contains": ["CNY"]}}),
            ]),
            dict(id="invalid-quantity", steps=[
                dict(action="fill", selector="#quantity", value="0"),
                dict(action="click", selector="#calculate", value="",
                     assertions={"#validation": {"contains": ["数量"]}}),
            ]),
        ],
        scope_note="Engineering publication gate only. Customer-specific pricing correctness is scored offline after terminal publication and never returned as repair feedback.",
    )


def seller_topics(case):
    scope = ["适用", "范围", "商品", "产品", "哪些", "对象", "客户", "scope", "item", "customer"]
    amount = ["比例", "折扣", "优惠", "价格", "多少", "几", "门槛", "数量", "阶梯",
              "threshold", "discount", "percent", "rate", "quantity"]
    compose = ["叠加", "顺序", "折后", "相加", "计算", "组合", "同时", "冲突", "优先",
               "更大", "选择", "precedence", "priority", "stack", "compound"]
    family = case["family"]
    if family == "quantity_tiers":
        pieces = [
            ("eligibility", scope, "只有A参加阶梯优惠，B和C始终原价；同一种商品两行的数量合并。"),
            ("thresholds", amount, "参加优惠的商品，少于5件无优惠，5至9件优惠10%，10件及以上优惠20%；选中的档位应用全部付费数量，不逐段计费。"),
        ]
    elif family == "customer_scope":
        pieces = [
            ("eligibility", scope, "客户优惠只针对A商品，B和C无优惠。"),
            ("customer_rates", amount + ["客户", "vip", "VIP", "合作"], "VIP客户优惠15%，合作客户优惠5%，普通客户无优惠。"),
        ]
    elif family == "validity_dates":
        pieces = [
            ("date_window", ["日期", "时间", "有效", "起止", "活动", "date", "valid"], "A商品仅在2026-03-01至2026-03-31优惠25%，包含起止当天；其他日期及B、C用原价。"),
        ]
    elif family == "compound_discounts":
        pieces = [
            ("discount_rates", amount, "第一项优惠10%，第二项优惠20%，适用于所有商品。"),
            ("composition", compose, "先减10%，再对第一次折后金额减20%；不能把百分比相加成30%。"),
        ]
    elif family == "overlap_priority":
        pieces = [
            ("eligibility", scope, "只有A参与客户和数量两种优惠，B、C用原价。"),
            ("rates_and_threshold", amount + ["vip", "VIP"], "VIP优惠10%；商品合计数量至少5件时批量优惠20%。"),
            ("priority", compose, "同时命中时VIP规则优先，只用VIP的10%；不叠加，也不自动选更大的20%。"),
        ]
    elif family == "mixed_threshold":
        pieces = [
            ("eligible_group", scope, "A和B属于同一优惠组，C不参与凑数也不享受优惠。"),
            ("combined_threshold", amount + ["合并", "合计"], "组内商品合计至少5件时，组内所有商品都优惠10%。"),
        ]
    elif family == "rate_override":
        pieces = [
            ("agreement_scope", scope, "协议价只适用合作客户购买A，其他客户和商品用目录价。"),
            ("agreement_rate", amount + ["替代", "协议"], "协议单价是88元，替代目录单价，不是减88或打88折；保留目录原金额，把价差计入价格调整金额。"),
        ]
    elif family == "tax_inclusive":
        pieces = [
            ("tax_rate", ["税率", "比例", "百分", "多少", "tax rate"], "本题只有一项10%的演示税，没有优惠。"),
            ("tax_basis", ["含税", "未税", "税前", "税后", "税额", "拆", "计算", "口径", "inclusive", "basis"],
             "目录单价均为含税价。未税金额为含税金额除以1.10，税额为两者差，最终应付保持原含税金额，不能重复加税。"),
        ]
    elif family == "net_total_discount":
        pieces = [
            ("fixed_discount", amount + ["基数", "整单", "税前", "税后"], "每张报价从整单未税金额先减30元，最多减到0；不是从含税总价减。"),
            ("tax_basis", ["税", "tax"], "目录单价不含税，先扣整单优惠，再对折后未税金额计算10%的演示税。"),
        ]
    elif family == "free_items":
        pieces = [
            ("eligible_product", scope, "只有A参与买赠，B和C不参与。"),
            ("gift_ratio", amount + ["赠", "买", "重复", "免费", "gift", "free"],
             "每买2件付费商品，额外赠1件同款，可重复，赠送数量向下取整。付费数量不含赠品，赠品单价0，应付只算付费商品。"),
        ]
    else:
        raise ValueError(family)
    return [dict(topic=topic, question_aliases=aliases, text=text) for topic, aliases, text in pieces]


def payloads(case):
    prices = case.get("prices", dict(A="100", B="60", C="200"))
    fixture = dict(
        schema_version="quotation-fixtures-v1", case_id=case["id"], industry="B2B",
        fixtures=dict(
            currency="CNY",
            catalogue=[dict(id=key, name=f"样例商品{key}", unit_price=value) for key, value in prices.items()],
            customers=[dict(id="standard", name="普通客户"), dict(id="vip", name="VIP客户"),
                       dict(id="partner", name="合作客户")],
            initial_date="2026-03-15",
        ), assets=[],
        engineering_conventions=COMMON_FACTS,
        data_provenance="Synthetic catalogue. No real customer, financial transaction, or production tax policy.",
    )
    raw = case["brief"] + COMMON_BRIEF
    answer = dict(
        case_id=case["id"], response_kind="frozen_synthetic_seller",
        answers=seller_topics(case),
        complete_rule_question_aliases=["完整规则", "所有规则", "具体业务规则", "完整定价", "具体定价规则",
                                        "full pricing rules", "complete rules"],
        fallback="页面布局与文案按常规自行决定。商品和客户样例由本地testdata提供。只需澄清影响计算结果的业务规则；未规定的其他优惠均不适用。",
    )
    private = dict(
        case_id=case["id"], split=case["split"], family=case["family"],
        rule_config=case["rules"], catalogue=fixture["fixtures"]["catalogue"],
        vectors=case["vectors"],
        negative_vectors=[dict(id="zero-first", quantity="0", second_quantity="0"),
                          dict(id="negative-second", quantity="1", second_quantity="-1"),
                          dict(id="fractional-first", quantity="1.5", second_quantity="0")],
        acceptance_rule="All positive vectors match every monetary and free-quantity output; invalid quantities show validation; repeated calculation and reverse edits do not accumulate; no runtime page errors. Unpublished case fails end-to-end.",
    )
    public = dict(id=case["id"], split=case["split"], title=case["title"],
                  raw_sales_brief=raw, family=case["family"], source_urls=case["source_urls"],
                  initial_information=case.get("initial_information", "underspecified"),
                  provenance="documentation-derived requirement; synthetic configured business preferences",
                  testdata_path=f"testdata/{case['id']}",
                  seller_script=f"seller-answers/{case['id']}.json",
                  private_acceptance=f"private/{case['id']}.json",
                  positive_vector_count=len(case["vectors"]), negative_vector_count=3)
    return public, fixture, answer, private


def write_new(path, value):
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"Refusing to overwrite changed dataset artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    cases = []
    files = []
    for definition in definitions():
        public, fixture, answer, private = payloads(definition)
        cases.append(public)
        artifacts = {
            ROOT / public["testdata_path"] / "inputs.json": fixture,
            ROOT / public["testdata_path"] / "acceptance.json": engineering_contract(public["id"]),
            DATASET / public["seller_script"]: answer,
            DATASET / public["private_acceptance"]: private,
        }
        for path, value in artifacts.items():
            write_new(path, value)
            files.append(path)
    case_path = DATASET / "cases.json"
    write_new(case_path, dict(schema_version="quotation-intent-v1", cases=cases,
                             split_policy="4 development / 6 heldout, declared before any model generation",
                             provenance="Public business rule families plus synthetic parameters; no actual customer interviews."))
    files.append(case_path)
    manifest = dict(schema_version="quotation-intent-manifest-v1",
                    files={str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in files})
    write_new(DATASET / "manifest.json", manifest)
    print(json.dumps(dict(cases=len(cases), development=4, heldout=6,
                          positive_vectors=sum(c["positive_vector_count"] for c in cases),
                          negative_vectors=30, dataset=str(DATASET)), ensure_ascii=False))


if __name__ == "__main__":
    main()
