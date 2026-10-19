# sales-v3-024 经销客户优惠优先级·方案4
分组：heldout；难度：simple；场景组：family-05

## 销售原话
给销售做一个经销客户优惠优先级演示，会员和数量优惠有优先级，需要审批后让客户确认。三款演示商品为A：经销客户优惠基础包，单价125.95元；B：经销客户优惠扩展包，单价87.50元；C：经销客户优惠专业包，单价188.99元。仅商品A：会员vip固定优惠8%，优先于数量优惠；非vip达到8件优惠18%；即使vip优惠更小也优先用vip，不叠加、不自动挑最便宜。经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。不需要配送，没有额外运费。仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：经销客户优惠基础包，单价125.95元；B：经销客户优惠扩展包，单价87.50元；C：经销客户优惠专业包，单价188.99元。
- pricing：仅商品A：会员vip固定优惠8%，优先于数量优惠；非vip达到8件优惠18%；即使vip优惠更小也优先用vip，不叠加、不自动挑最便宜。
- workflow：经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-024/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-024.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计125.95、优惠0.00、税0.00、合计125.95、赠品0
- 5件A：小计629.75、优惠0.00、税0.00、合计629.75、赠品0
- 11件A：小计1385.45、优惠249.38、税0.00、合计1136.07、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
