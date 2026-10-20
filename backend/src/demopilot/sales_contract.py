"""User-confirmed quotation rules, separate from the frozen benchmark cases."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .business_fields import Clarification
from .quotation_capabilities import BUSINESS_FIELDS, PRICING_FIELDS, WORKFLOWS, render_capabilities

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
    questions: list[str] = Field(default_factory=list, max_length=3)
    clarifications: list[Clarification] = Field(default_factory=list, max_length=3)
    proposal: QuotePlan | None
    source_quotes: list[str] = Field(max_length=12)

    @model_validator(mode="after")
    def ready_has_rules(self):
        if self.clarifications:
            rendered = [item.question for item in self.clarifications]
            if self.questions and self.questions != rendered:
                raise ValueError("问题文字必须与业务字段问题一一对应")
            self.questions = rendered
            fields = [field for item in self.clarifications for field in item.field_ids]
            if len(fields) != len(set(fields)):
                raise ValueError("同轮不重复询问同一业务字段")
        if self.status == "ready" and (
            self.proposal is None or self.questions or self.clarifications or not self.source_quotes
        ):
            raise ValueError("可确认的意图必须包含完整规则、引用来源且没有未解决问题")
        if self.status == "unsupported":
            if self.proposal is not None or self.clarifications:
                raise ValueError("无法支持的需求不能携带可构建方案")
            if not self.questions:
                # A refusal is a valid terminal decision, not missing output.
                # Preserve the model's reason and show the actual product scope.
                self.questions = [
                    f"{self.title}。当前仅支持 A/B/C 三款商品、一个定价方案及一个审批流程的本地演示，"
                    "不提供真实支付或生产身份鉴权。是否愿意在保留这些限制的前提下调整需求？"
                ]
        if self.status == "needs_details" and (not self.clarifications or self.proposal is not None):
            raise ValueError("信息不足时必须提供对应业务字段的问题，不能携带可构建方案")
        return self


def validate_capability_schema():
    """Fail before startup when typed rules and the shared capability drift."""
    schema = QuotePlan.model_json_schema()
    mapping = schema["properties"]["pricing_rule"]["discriminator"]["mapping"]
    if set(mapping) != set(PRICING_FIELDS):
        raise RuntimeError("Pricing capabilities differ from the typed business contract")
    for kind, reference in mapping.items():
        required = set(schema["$defs"][reference.rsplit("/", 1)[-1]]["required"]) - {"kind"}
        if required != set(PRICING_FIELDS[kind]):
            raise RuntimeError(f"Pricing capability fields differ for {kind}")
    if set(schema["properties"]["workflow"]["enum"]) != set(WORKFLOWS):
        raise RuntimeError("Workflow capabilities differ from the typed business contract")
    if any(path.split(".")[0] not in QuotePlan.model_fields for path in BUSINESS_FIELDS):
        raise RuntimeError("Clarification field does not belong to the business contract")
    return True


validate_capability_schema()


INTAKE_INSTRUCTION = """你是DemoPilot报价需求澄清模块。仅依据销售对话和下面共用能力说明理解需求，不读写文件、不调用工具。
能力、默认值、计价与审批语义以这份共用说明为准；Core接收同一版本。产品已有默认值不需要销售选择，销售必须提供的业务事实不能猜测。
输出needs_details时，proposal=null；clarifications最多3个问题，每个包括question、field_ids和reason（missing或conflict）。field_ids必须来自business_fields，且真正对应该问题要取得或澄清的业务事实；可同时询问一组相关字段。
自然语言可以自由表达，事实交付依据field_ids，不依据问句关键词。每轮不重复询问同一字段。questions可省略或[]，服务器会按clarifications生成展示文字；不能只输出无字段的questions。
已给出的信息保留并整合；部分回答后只问仍缺的字段。存在同一字段的实际冲突时reason=conflict，指出具体冲突，不能自动同意新价格或替销售选择规则。
同一字段的多轮澄清仍引用原事实，不能把已经问过当成已经解决。不得询问共用说明里的产品默认字段或无关外观。
规则齐全返回ready、clarifications=[]、questions=[]，proposal为完整确认结构。source_quotes逐字摘自销售消息，覆盖价格、计价和审批依据；输出前核对每个业务值及引用，不用共用产品默认值替代未知销售事实。
无法表达的真实业务返回unsupported、proposal=null、clarifications=[]并在title/questions说明范围，不将规则偷偷改成支持的另一种。用户确认前不开始构建。
最终只返回以下JSON Schema对应的直接JSON对象，不使用Markdown。
""" + "\n" + render_capabilities()
