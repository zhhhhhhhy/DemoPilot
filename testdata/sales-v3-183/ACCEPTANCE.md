# sales-v3-183 优先优惠报价过期保护·方案3
分组：heldout；难度：hard；场景组：family-37

## 销售原话
给销售做一个优先优惠报价过期保护演示，会员和数量优惠有优先级，需要审批后让客户确认。仅商品C：会员vip固定优惠7%，优先于数量优惠；非vip达到7件优惠17%；即使vip优惠更小也优先用vip，不叠加、不自动挑最便宜。客户只能在报价有效期内确认；每次有效变更使旧审批失效，重新提交后才可批准。报价最迟在2026-03-27（含当日）由客户确认，次日不能确认；用独立的模拟当前日期判断。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：优先优惠报价基础包，单价214.95元；B：优先优惠报价扩展包，单价114.50元；C：优先优惠报价专业包，单价249.99元。
- pricing：仅商品C：会员vip固定优惠7%，优先于数量优惠；非vip达到7件优惠17%；即使vip优惠更小也优先用vip，不叠加、不自动挑最便宜。
- workflow：客户只能在报价有效期内确认；每次有效变更使旧审批失效，重新提交后才可批准。报价最迟在2026-03-27（含当日）由客户确认，次日不能确认；用独立的模拟当前日期判断。
- shipping：需要配送：自提pickup为0元，普通standard为18元，加急express为45元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-183/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-183.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计214.95、优惠0.00、税0.00、合计214.95、赠品0
- 5件A：小计1074.75、优惠0.00、税0.00、合计1074.75、赠品0
- 11件A：小计2364.45、优惠0.00、税0.00、合计2364.45、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
