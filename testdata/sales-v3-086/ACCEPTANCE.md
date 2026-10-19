# sales-v3-086 合作客户两级审批·方案1
分组：development；难度：medium；场景组：family-18

## 销售原话
给销售做一个合作客户两级审批演示，不同客户优惠不同，需要审批后让客户确认。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：合作客户两级基础包，单价143.95元；B：合作客户两级扩展包，单价85.50元；C：合作客户两级专业包，单价205.99元。
- pricing：仅商品A按客户类别优惠：普通standard优惠0%、会员vip优惠9%、合作partner优惠16%；其他商品原价。
- workflow：经理、财务依次审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-086/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-086.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计143.95、优惠0.00、税0.00、合计143.95、赠品0
- 5件A：小计719.75、优惠0.00、税0.00、合计719.75、赠品0
- 11件A：小计1583.45、优惠0.00、税0.00、合计1583.45、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
