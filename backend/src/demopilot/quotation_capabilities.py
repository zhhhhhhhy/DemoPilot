"""Versioned quotation capability contract shared by intake, Core and checks."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

CAPABILITY_VERSION = "quotation-fields-v1"
DEFAULT_DAY = "2026-03-15"

WORKFLOWS = {
    "single_manager": "经理审批后由客户确认",
    "two_stage": "经理、财务依次审批后由客户确认",
    "threshold": "经理审批，达到金额门槛时追加财务审批",
    "dual_manager": "两位不同经理会签后由客户确认",
    "rejection_reason": "驳回必须填写原因，修改后重新提交",
    "cancel_amend": "取消后允许销售修订重提",
    "customer_owner": "仅指定客户可以确认",
    "expiry": "客户只能在报价有效期内确认",
    "record_persistence": "报价记录及审批在刷新后保留",
    "manual_override": "允许销售调整商品 A 单价，修改后重新审批",
}

_UI_TEMPLATE = """# Confirmed quotation application interface

Implement the exact catalogue, pricing profile(s), workflow and optional shipping in JSON. Profile keys and product IDs are selector values; display friendly Chinese labels and the confirmed product names. There are no other discounts or taxes. Prices use full precision then independent half-up two-decimal display rounding. Tax-inclusive subtotal is rounded before residual tax. Quantity tiers apply to all paid units, not progressive bands. Free units do not add charged units.

Required interface:
- selects #profile (only JSON profiles), #product/#second-product (A/B/C), #customer (standard/vip/partner), #record (Q1/Q2), #role (seller/manager/finance/customer), #actor (seller1/manager1/manager2/finance1/client1/intruder).
- inputs #quantity initially1, #second-quantity initially0, #date initially{simulation_day}, #reason initiallyempty, #today initially{simulation_day} (simulated current day, separate from quote date).
- Initial profile is the FIRST declared JSON profile; productA, second-productB, customerstandard, recordQ1, roleseller, actorseller1. All amounts reflect initial values; stateDraft, revision0, approved-revision -1, history-count0.
- buttons #calculate, #submit, #approve, #reject, #accept, #cancel, #amend. Wrong/repeated/out-of-order actions preserve all committed values and history, showing #error; disabled actions are acceptable. No external submission.
- visible outputs #subtotal, #discount, #tax, #total with EXACT two-decimal money strings and no currency symbols; #free-quantity, #revision, #approved-revision, #history-count integer strings; #state uses exact codes Draft/PendingManager/PendingFinance/Approved/Rejected/Accepted/Cancelled.
- If contract version2, #shipping select pickup/standard/express initiallypickup and output #freight. Use confirmed charges, once per quote AFTER discounts and tax, include in approval threshold. Otherwise do not add shipping requirements. manual_override alone adds #manual-rate input initiallyempty.

Shared state rules:
Two independently stored quotes Q1/Q2; form changes are STAGED until Calculate. Switching record restores that quote. Product/quantity/customer/profile/date/manual-rate/shipping changes commit only via Calculate by seller; quantity integers, first>=1/second>=0; invalid or wrong-role commits change nothing. A genuinely changed quote increments revision AND history once, resets Draft, clears all approval, approved-revision=-1. Same-value recalculation does not accumulate discounts or history. Editing Accepted/Cancelled is forbidden.
Seller Submit from Draft/Rejected ->PendingManager, history+1, clears approvals. Manager Approve PendingManager ->Approved (or workflow's next step); finance cannot substitute for manager. Final approval sets approved-revision=current revision. Manager Reject PendingManager or finance Reject PendingFinance ->Rejected, clears approvals; history+1. Customer Accept only Approved ->Accepted. Seller Cancel except Accepted/Cancelled ->Cancelled and clears approvals. Each successful state transition including a partial manager approval adds exactly1 history; rejection/duplicate actions add0. Same manager actor cannot approve twice. Role/actor/reason/today/selected-record changes alone never alter quote history.

Selected workflow only:
single_manager: shared manager flow.
two_stage: manager ->PendingFinance, finance ->Approved.
threshold: after manager, total>=approval_threshold ->PendingFinance elseApproved.
dual_manager: manager1 first remainsPendingManager; repeating manager1 denied; manager2 completesApproved.
rejection_reason: Reject requires a nonempty trimmed reason; fixing/resubmitting clears approvals.
cancel_amend: seller Amend fromCancelled ->Draft, revision+1/history+1, retain fields and clear approvals.
customer_owner: Accept requires customer role AND client1 actor; intruder denied.
expiry: Accept requires today<=valid_until, including boundary; changing today alone does not mutate quote.
record_persistence: persist each quote's fields, amounts, state, revisions, history, approvers across reload; reload resets selected record/role/actor toQ1/seller/seller1. Other workflows need in-page isolation; persistence optional.
manual_override: positive manual-rate replaces A unit rate before pricing and persists on later recalculation; configured customer protocol rate takes precedence for rate_override; nonpositive manual rate invalid.

Pricing details are in JSON. For rate_override, Subtotal uses original catalogue/manual prices, the rate difference appears in Discount. Do not change confirmed prices or business rules to satisfy a test. Use only local files, no remote requests. Keep scripts in app.js, styles in styles.css, no inline event handlers. The parent owns trusted tests and publishing; implement and self-test until those checks pass or report the unmet goal.
"""

UI_CONTRACT = _UI_TEMPLATE.replace("{simulation_day}", DEFAULT_DAY)

# Product defaults never become missing business facts for the salesperson.
FORM_DEFAULTS = dict(
    profile="quantity_tiers", product="A", quantity="1", second_product="B",
    second_quantity="0", customer="standard", date=DEFAULT_DAY, manual_rate="", shipping="pickup",
)
ROLE_DEFAULTS = dict(record="Q1", role="seller", actor="seller1", reason="", today=DEFAULT_DAY)

PRICING_FIELDS = {
    "quantity_tiers": ("product", "tiers"),
    "customer_scope": ("product", "discounts"),
    "validity_dates": ("product", "start", "end", "percent"),
    "compound_discounts": ("percents",),
    "overlap_priority": ("product", "vip_percent", "volume_minimum", "volume_percent", "priority"),
    "mixed_threshold": ("products", "minimum", "percent"),
    "rate_override": ("product", "customer", "rate"),
    "tax_inclusive": ("tax_percent",),
    "net_total_discount": ("amount", "tax_percent"),
    "free_items": ("product", "buy", "free"),
}

# Semantic business paths, not Chinese aliases or example IDs.
BUSINESS_FIELDS = {
    "catalogue": dict(topic="catalogue", label="三款商品的名称与目录单价", policy="sales_required"),
    "pricing_rule": dict(topic="pricing", label="本次采用的完整计价规则", policy="sales_required"),
    "workflow": dict(topic="workflow", label="审批角色、顺序及客户确认要求", policy="sales_required"),
    "approval_threshold": dict(topic="workflow", label="追加财务审批金额门槛", policy="required_for_threshold"),
    "valid_until": dict(topic="workflow", label="客户确认截止日（含当日）", policy="required_for_expiry"),
    "shipping": dict(topic="shipping", label="是否配送及各配送方式费用", policy="optional_sales"),
}
for product in ("A", "B", "C"):
    for key, label in (("name", "名称"), ("unit_price", "目录单价")):
        BUSINESS_FIELDS[f"catalogue.{product}.{key}"] = dict(
            topic="catalogue", label=f"商品{product}的{label}", policy="sales_required",
        )
for key in ("kind", *sorted({f for fields in PRICING_FIELDS.values() for f in fields})):
    BUSINESS_FIELDS[f"pricing_rule.{key}"] = dict(
        topic="pricing", label=f"计价规则字段{key}", policy="required_by_pricing_kind",
    )
for key in ("pickup", "standard", "express"):
    BUSINESS_FIELDS[f"shipping.{key}"] = dict(
        topic="shipping", label=f"{key}配送方式费用", policy="required_if_shipping",
    )


def capability_manifest():
    return deepcopy(dict(
        version=CAPABILITY_VERSION,
        scope="Offline quotation, exactly A/B/C, one pricing policy and one workflow; no real payments or production identity.",
        business_fields=BUSINESS_FIELDS, pricing_fields=PRICING_FIELDS, workflows=WORKFLOWS,
        product_defaults=dict(form=FORM_DEFAULTS, controls=ROLE_DEFAULTS, currency="CNY",
                              integer_quantities=True, extra_taxes_or_discounts=False),
        field_policy="Ask only missing/conflicting sales facts. Product defaults are already defined; do not ask sales to choose them. Optional shipping defaults to null unless requested.",
        workflow_selection="每个workflow是完整流程模板；所有模板包含客户确认与有效变更后重新审批。只选择用户明确要求的专属客户、取消重开、过期或刷新持久化限制；普通客户确认不代表专属客户限制。",
        money_policy="十进制全精度计算，显示时独立四舍五入两位。含税拆分保留原含税总价：未税小计先四舍五入，税额为原含税金额减已显示小计；不重复加税，也不是从舍入字段反算总价。先判断表述是否数值兼容；真实不相容金额或算法必须澄清，不能擅改规则。",
        sample_catalogue_policy="商品名称和价格来自销售；只有明确同意默认样例时才可用A=100/B=60/C=200，不能因未提供而自行采用。",
        initial_profile_policy="Use the first confirmed profile. The form profile placeholder is not a default business pricing rule; pricing_rule is always a sales fact.",
        shared_ui_and_business_rules=UI_CONTRACT,
    ))


def capability_identity():
    data = json.dumps(capability_manifest(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return dict(version=CAPABILITY_VERSION, sha256=hashlib.sha256(data.encode()).hexdigest())


def render_capabilities():
    """Send exactly the same versioned specification to intake and Core."""
    return "# Shared quotation capabilities\n" + json.dumps(
        dict(identity=capability_identity(), capabilities=capability_manifest()),
        ensure_ascii=False, indent=2,
    ) + "\n"
