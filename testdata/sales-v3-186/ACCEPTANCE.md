# sales-v3-186 减免税费多报价刷新·方案1
分组：validation；难度：hard；场景组：family-38

## 销售原话
给销售做一个减免税费多报价刷新演示，整单减钱再算税，需要审批后让客户确认。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：减免税费多报基础包，单价203.95元；B：减免税费多报扩展包，单价105.50元；C：减免税费多报专业包，单价245.99元。
- pricing：整单先减免12.50元，最多减到0；再对减免后金额加6%税，税四舍五入两位，不按减免前金额计税。
- workflow：报价记录及审批在刷新后保留；每次有效变更使旧审批失效，重新提交后才可批准。Q1/Q2各自的金额、审批、修订和历史在刷新后保留，刷新选回Q1、销售seller1。
- shipping：需要配送：自提pickup为0元，普通standard为12元，加急express为35元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-186/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-186.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计203.95、优惠12.50、税11.49、合计202.94、赠品0
- 5件A：小计1019.75、优惠12.50、税60.44、合计1067.69、赠品0
- 11件A：小计2243.45、优惠12.50、税133.86、合计2364.81、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/applying-discount

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
