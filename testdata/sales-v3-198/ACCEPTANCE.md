# sales-v3-198 合并数量多报价刷新·方案3
分组：heldout；难度：hard；场景组：family-40

## 销售原话
给销售做一个合并数量多报价刷新演示，几类商品一起凑数量，需要审批后让客户确认。商品C和A的数量合并达到8件，才对这些商品小计优惠11%；未指定商品不凑数也不优惠。报价记录及审批在刷新后保留；每次有效变更使旧审批失效，重新提交后才可批准。Q1/Q2各自的金额、审批、修订和历史在刷新后保留，刷新选回Q1、销售seller1。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：合并数量多报基础包，单价223.95元；B：合并数量多报扩展包，单价117.50元；C：合并数量多报专业包，单价255.99元。
- pricing：商品C和A的数量合并达到8件，才对这些商品小计优惠11%；未指定商品不凑数也不优惠。
- workflow：报价记录及审批在刷新后保留；每次有效变更使旧审批失效，重新提交后才可批准。Q1/Q2各自的金额、审批、修订和历史在刷新后保留，刷新选回Q1、销售seller1。
- shipping：需要配送：自提pickup为0元，普通standard为18元，加急express为45元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-198/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-198.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计223.95、优惠0.00、税0.00、合计223.95、赠品0
- 5件A：小计1119.75、优惠0.00、税0.00、合计1119.75、赠品0
- 11件A：小计2463.45、优惠270.98、税0.00、合计2192.47、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
