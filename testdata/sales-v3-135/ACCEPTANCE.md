# sales-v3-135 手工单价与客户类别·方案5
分组：heldout；难度：medium；场景组：family-27

## 销售原话
给销售做一个手工单价与客户类别演示，不同客户优惠不同，需要审批后让客户确认。细节要问我，不能自行选默认价格或忽略边界。允许销售调整商品 A 单价，修改后重新审批；每次有效变更使旧审批失效，重新提交后才可批准。销售可手工修改A单价，后续重算保留；非正数拒绝，修改必须重新审批。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：手工单价与客基础包，单价198.95元；B：手工单价与客扩展包，单价114.50元；C：手工单价与客专业包，单价235.99元。
- pricing：仅商品B按客户类别优惠：普通standard优惠0%、会员vip优惠13%、合作partner优惠12%；其他商品原价。
- workflow：允许销售调整商品 A 单价，修改后重新审批；每次有效变更使旧审批失效，重新提交后才可批准。销售可手工修改A单价，后续重算保留；非正数拒绝，修改必须重新审批。
- shipping：需要配送：自提pickup为0元，普通standard为24元，加急express为55元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-135/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-135.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计198.95、优惠0.00、税0.00、合计198.95、赠品0
- 5件A：小计994.75、优惠0.00、税0.00、合计994.75、赠品0
- 11件A：小计2188.45、优惠0.00、税0.00、合计2188.45、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://www.odoo.com/documentation/17.0/applications/sales/sales/products_prices/prices/pricing.html

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
