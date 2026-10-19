# sales-v3-171 活动日期与确认截止·方案1
分组：development；难度：hard；场景组：family-35

## 销售原话
给销售做一个活动日期与确认截止演示，活动期内才优惠，需要审批后让客户确认。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：活动日期与确基础包，单价194.95元；B：活动日期与确扩展包，单价102.50元；C：活动日期与确专业包，单价239.99元。
- pricing：仅商品A在报价日期2026-03-04至2026-03-20（首尾均包含）优惠7%；日期以外恢复原价。
- workflow：客户只能在报价有效期内确认；每次有效变更使旧审批失效，重新提交后才可批准。报价最迟在2026-03-25（含当日）由客户确认，次日不能确认；用独立的模拟当前日期判断。
- shipping：需要配送：自提pickup为0元，普通standard为12元，加急express为35元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-171/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-171.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计194.95、优惠13.65、税0.00、合计181.30、赠品0
- 5件A：小计974.75、优惠68.23、税0.00、合计906.52、赠品0
- 11件A：小计2144.45、优惠150.11、税0.00、合计1994.34、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
