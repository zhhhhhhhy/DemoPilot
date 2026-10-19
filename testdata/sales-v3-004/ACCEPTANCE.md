# sales-v3-004 办公耗材批量报价·方案4
分组：development；难度：simple；场景组：family-01

## 销售原话
给销售做一个办公耗材批量报价演示，买得多有优惠，需要审批后让客户确认。三款演示商品为A：办公耗材批量基础包，单价113.95元；B：办公耗材批量扩展包，单价83.50元；C：办公耗材批量专业包，单价180.99元。仅商品A按数量优惠：满6件优惠13%，满11件优惠21%；命中最高优惠档，对该商品全部付费数量生效，不分段、不叠加，同商品两行合并数量。经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。不需要配送，没有额外运费。仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：办公耗材批量基础包，单价113.95元；B：办公耗材批量扩展包，单价83.50元；C：办公耗材批量专业包，单价180.99元。
- pricing：仅商品A按数量优惠：满6件优惠13%，满11件优惠21%；命中最高优惠档，对该商品全部付费数量生效，不分段、不叠加，同商品两行合并数量。
- workflow：经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-004/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-004.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计113.95、优惠0.00、税0.00、合计113.95、赠品0
- 5件A：小计569.75、优惠0.00、税0.00、合计569.75、赠品0
- 11件A：小计1253.45、优惠263.22、税0.00、合计990.23、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
