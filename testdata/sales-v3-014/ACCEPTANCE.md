# sales-v3-014 展会活动期报价·方案4
分组：development；难度：simple；场景组：family-03

## 销售原话
给销售做一个展会活动期报价演示，活动期内才优惠，需要审批后让客户确认。三款演示商品为A：展会活动期报基础包，单价119.95元；B：展会活动期报扩展包，单价85.50元；C：展会活动期报专业包，单价184.99元。仅商品A在报价日期2026-03-07至2026-03-23（首尾均包含）优惠13%；日期以外恢复原价。经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。不需要配送，没有额外运费。仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：展会活动期报基础包，单价119.95元；B：展会活动期报扩展包，单价85.50元；C：展会活动期报专业包，单价184.99元。
- pricing：仅商品A在报价日期2026-03-07至2026-03-23（首尾均包含）优惠13%；日期以外恢复原价。
- workflow：经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-014/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-014.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计119.95、优惠15.59、税0.00、合计104.36、赠品0
- 5件A：小计599.75、优惠77.97、税0.00、合计521.78、赠品0
- 11件A：小计1319.45、优惠171.53、税0.00、合计1147.92、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
