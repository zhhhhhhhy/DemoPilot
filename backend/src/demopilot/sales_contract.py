"""User-confirmed quotation rules, separate from the frozen benchmark cases."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProductId = Literal["A", "B", "C"]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=8, decimal_places=4)]
Amount = Annotated[Decimal, Field(ge=0, le=100000000, max_digits=14, decimal_places=4)]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Product(ClosedModel):
    id: ProductId
    name: str = Field(min_length=1, max_length=60)
    unit_price: Amount = Field(gt=0)


class Tier(ClosedModel):
    minimum: int = Field(ge=1, le=1000000)
    percent: Percent


class QuantityRule(ClosedModel):
    kind: Literal["quantity_tiers"]
    product: ProductId
    tiers: list[Tier] = Field(min_length=1, max_length=8)


class CustomerRule(ClosedModel):
    kind: Literal["customer_scope"]
    product: ProductId
    discounts: dict[Literal["standard", "vip", "partner"], Percent] = Field(min_length=1)


class DateRule(ClosedModel):
    kind: Literal["validity_dates"]
    product: ProductId
    start: date
    end: date
    percent: Percent

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.end < self.start:
            raise ValueError("活动结束日期不能早于开始日期")
        return self


class CompoundRule(ClosedModel):
    kind: Literal["compound_discounts"]
    percents: list[Percent] = Field(min_length=1, max_length=5)


class PriorityRule(ClosedModel):
    kind: Literal["overlap_priority"]
    product: ProductId
    vip_percent: Percent
    volume_minimum: int = Field(ge=1, le=1000000)
    volume_percent: Percent
    priority: Literal["vip"]


class MixedRule(ClosedModel):
    kind: Literal["mixed_threshold"]
    products: list[ProductId] = Field(min_length=2, max_length=3)
    minimum: int = Field(ge=1, le=1000000)
    percent: Percent


class RateRule(ClosedModel):
    kind: Literal["rate_override"]
    product: ProductId
    customer: Literal["standard", "vip", "partner"]
    rate: Amount = Field(gt=0)


class InclusiveRule(ClosedModel):
    kind: Literal["tax_inclusive"]
    tax_percent: Percent


class NetRule(ClosedModel):
    kind: Literal["net_total_discount"]
    amount: Amount
    tax_percent: Percent


class FreeRule(ClosedModel):
    kind: Literal["free_items"]
    product: ProductId
    buy: int = Field(ge=1, le=1000000)
    free: int = Field(ge=1, le=1000000)


PricingRule = Annotated[
    QuantityRule
    | CustomerRule
    | DateRule
    | CompoundRule
    | PriorityRule
    | MixedRule
    | RateRule
    | InclusiveRule
    | NetRule
    | FreeRule,
    Field(discriminator="kind"),
]

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


class QuotePlan(ClosedModel):
    title: str = Field(min_length=1, max_length=100)
    catalogue: list[Product] = Field(min_length=3, max_length=3)
    pricing_rule: PricingRule
    workflow: Literal[
        "single_manager",
        "two_stage",
        "threshold",
        "dual_manager",
        "rejection_reason",
        "cancel_amend",
        "customer_owner",
        "expiry",
        "record_persistence",
        "manual_override",
    ]
    approval_threshold: Amount | None = None
    valid_until: date | None = None
    shipping: dict[Literal["pickup", "standard", "express"], Amount] | None = None

    @model_validator(mode="after")
    def coherent(self):
        if {p.id for p in self.catalogue} != {"A", "B", "C"}:
            raise ValueError("请确认三款演示商品 A、B、C 的名称和单价")
        if self.workflow == "threshold" and self.approval_threshold is None:
            raise ValueError("需要确认财务审批的金额门槛")
        if self.workflow == "expiry" and self.valid_until is None:
            raise ValueError("需要确认报价有效期")
        if self.shipping is not None:
            if (
                set(self.shipping) != {"pickup", "standard", "express"}
                or self.shipping["pickup"] != 0
            ):
                raise ValueError("配送需明确自提 0 元、普通配送和加急配送金额")
        if isinstance(self.pricing_rule, QuantityRule):
            minima = [t.minimum for t in self.pricing_rule.tiers]
            if len(set(minima)) != len(minima):
                raise ValueError("数量优惠门槛不能重复")
        if isinstance(self.pricing_rule, MixedRule) and len(set(self.pricing_rule.products)) != len(
            self.pricing_rule.products
        ):
            raise ValueError("合并计数商品不能重复")
        return self

    def contract(self, project: str) -> dict:
        rule = self.pricing_rule.model_dump(mode="json")
        key = rule["kind"]
        contract = {
            "schema_version": "quotation-business-contract-v2",
            "id": project,
            "title": self.title,
            "version": 2 if self.shipping is not None else 1,
            "workflow": self.workflow,
            "profiles": {key: rule},
            "catalogue": [p.model_dump(mode="json") for p in self.catalogue],
            "approval_threshold": str(self.approval_threshold or 0),
            "valid_until": str(self.valid_until or date(2099, 12, 31)),
            "boundary_vectors": {key: self.boundaries()},
        }
        if self.shipping is not None:
            contract["shipping"] = {k: str(v) for k, v in self.shipping.items()}
        return contract

    def boundaries(self) -> list[dict]:
        rule = self.pricing_rule.model_dump(mode="json")
        product = rule.get("product", "A")
        base = {"product": product, "second_quantity": "0"}
        kind = rule["kind"]
        if kind == "quantity_tiers":
            values = sorted({max(1, t["minimum"] + d) for t in rule["tiers"] for d in (-1, 0, 1)})
            return [dict(base, quantity=str(q)) for q in values]
        if kind == "validity_dates":
            start, end = date.fromisoformat(rule["start"]), date.fromisoformat(rule["end"])
            return [
                dict(base, date=str(day), quantity="2")
                for day in (start - timedelta(days=1), start, end, end + timedelta(days=1))
            ]
        if kind in {"customer_scope", "rate_override"}:
            return [dict(base, quantity="6", customer=c) for c in ("standard", "vip", "partner")]
        if kind == "overlap_priority":
            return [
                dict(base, quantity=str(q), customer=c)
                for q, c in (
                    (max(1, rule["volume_minimum"] - 1), "standard"),
                    (rule["volume_minimum"], "standard"),
                    (rule["volume_minimum"], "vip"),
                )
            ]
        if kind == "mixed_threshold":
            a, b = rule["products"][:2]
            return [
                dict(
                    product=a,
                    quantity="1",
                    second_product=b,
                    second_quantity=str(max(0, rule["minimum"] - 1 + d)),
                )
                for d in (-1, 0, 1)
            ]
        if kind == "free_items":
            return [dict(base, quantity=str(max(1, rule["buy"] + d))) for d in (-1, 0, 1)]
        return [dict(base, quantity=q) for q in ("1", "3", "11")]

    def summary(self) -> list[str]:
        rule = self.pricing_rule.model_dump(mode="json")
        kind = rule["kind"]
        labels = {
            "quantity_tiers": "按数量门槛优惠（命中档位适用于全部数量）",
            "customer_scope": "按客户类别优惠",
            "validity_dates": "活动日期内优惠",
            "compound_discounts": "依次计算多重折扣",
            "overlap_priority": "VIP 优惠优先，不叠加数量优惠",
            "mixed_threshold": "指定商品合并数量优惠",
            "rate_override": "客户协议价",
            "tax_inclusive": "含税价反算未税金额",
            "net_total_discount": "整单减免后计税",
            "free_items": "买赠数量与付费数量分开",
        }
        lines = ["；".join(f"{p.id}（{p.name}）{p.unit_price} 元" for p in self.catalogue)]
        details = "; ".join(f"{k}={v}" for k, v in rule.items() if k != "kind")
        if kind == "quantity_tiers":
            details = "；".join(
                f"{rule['product']} 满 {t['minimum']} 件优惠 {t['percent']}%" for t in rule["tiers"]
            )
        elif kind == "customer_scope":
            details = "；".join(
                f"{c} 客户购买 {rule['product']} 优惠 {p}%" for c, p in rule["discounts"].items()
            )
        lines.extend([f"{labels[kind]}：{details}", WORKFLOWS[self.workflow]])
        if self.workflow == "threshold":
            lines.append(f"追加财务审批门槛：{self.approval_threshold} 元（含等于）")
        if self.workflow == "expiry":
            lines.append(f"客户确认截止日期：{self.valid_until}（含当天）")
        if self.shipping:
            lines.append(
                f"配送：自提 0 元，普通 {self.shipping['standard']} 元，加急 {self.shipping['express']} 元；整单只加一次"
            )
        lines.append("金额按整单计算后四舍五入到两位；无额外税费或优惠；演示角色不代表生产鉴权")
        return lines


class IntakeResult(ClosedModel):
    status: Literal["needs_details", "ready", "unsupported"]
    title: str = Field(min_length=1, max_length=100)
    questions: list[str] = Field(max_length=5)
    proposal: QuotePlan | None
    source_quotes: list[str] = Field(max_length=12)

    @model_validator(mode="after")
    def ready_has_rules(self):
        if self.status == "ready" and (
            self.proposal is None or self.questions or not self.source_quotes
        ):
            raise ValueError("可确认的意图必须包含完整规则、引用来源且没有未解决问题")
        if self.status != "ready" and not self.questions:
            raise ValueError("信息不足时必须指出需要用户回答的问题")
        return self


INTAKE_INSTRUCTION = """你是 DemoPilot 报价需求澄清模块。仅依据用户对话识别规则，不读写文件、不调用工具。
当前支持本地离线报价演示、三款演示商品 A/B/C、一个定价方案及一个审批流程。不是生产 ERP，也不是其他类型应用。
用户没有给出的商品单价、优惠门槛、折扣、税率、审批顺序，必须询问，不能从历史评测或常识猜测。
三款商品可由用户提供；只有用户明确同意默认演示样例时，才可采用 A=100/B=60/C=200。
缺信息返回 needs_details，每次集中问最多 3 个清晰问题，proposal=null。问商品样例和价格、具体计价规则、审批由谁以何顺序执行。
不追问无关的页面颜色、人民币币种或账期；本地演示约定人民币、无额外税费/折扣、数量为整数。
金额默认按完整精度计算、最终独立四舍五入两位；这与整单计价兼容。含税价拆分有已支持的特定顺序：固定原含税总价，未税小计先四舍五入两位，税额为原含税金额减已显示未税小计；这不是用显示字段反算总价，不要误判为超出能力或要求用户换算法。
区分通用舍入约定与具体方案的拆分步骤；核对当前税率和输入精度下数值是否兼容，不要仅因两种表述不同就反复追问。若用户对同一字段明确要求不相容的金额或两种不等价算法，必须指出具体冲突并询问确认，不能擅改规则或自动替用户选择。
discount percent 是优惠百分比：9折=优惠10%，8折=优惠20%。数量档位对该商品全部数量生效，不分段。
用户已给齐足够规则就返回 ready，questions=[]，proposal 给出严格结构，不继续询问已回答内容。
不要自动增加其他定价方案。workflow 按用户明确审批要求选择；仅说“审批”还不够，要问谁审批。
“一个审批流程”是以下一个完整模板，不是只允许一次审批动作。所有模板都允许审批后客户确认；有效变更使旧审批失效、重新提交后重批是公共规则：
- single_manager：销售提交，经理审批，客户确认。一般“经理审批后客户确认”选它。
- two_stage：销售提交，经理→财务依次审批，最后客户确认，包含变更后重新审批。
- threshold：经理审批，整单金额达到用户给定门槛时追加财务审批，最后客户确认。
- dual_manager：两位不同经理会签，禁止同一经理重复充数，最后客户确认。
- rejection_reason：经理可以批准或填写原因后驳回；销售修改并重提，再由经理审批，最后客户确认。
- cancel_amend：明确需要取消后可修订重开的流程；销售取消后可重开并重新经理审批，最后客户确认。
- customer_owner：经理审批后，仅指定的客户可确认。普通的“客户确认”不等于要求专属客户身份限制。
- expiry：经理审批后，客户只能在用户给定的报价确认截止日内确认；演示使用独立模拟当前日期，不用机器日期代替。
- record_persistence：经理审批和客户确认的报价记录、修订与历史在刷新后保留；普通多报价互不影响本身不代表必须刷新持久化。
- manual_override：销售可以手工修改A单价，修改后重走经理审批，最后客户确认；这与已选定价方案按既有公共规则协同。
不要因为“客户确认”或“修改后重批”就判定成多个不兼容流程。不要把普通重批误认作cancel_amend；未要求取消重开、专属客户、到期或刷新时不要擅加对应限制。
shipping 未要求就为 null，valid_until/approval_threshold 仅相应流程必须填写。当前无法表达的业务请明确提问澄清或 unsupported，不隐瞒遗漏。
source_quotes 必须逐字摘自用户消息，覆盖价格、定价和审批的依据。用户确认前不会开始构建。
最终仅返回符合以下 JSON Schema 的直接 JSON 对象，不使用 Markdown：
"""
