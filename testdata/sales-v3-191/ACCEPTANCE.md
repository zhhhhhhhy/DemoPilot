# sales-v3-191 含税金额多报价刷新·方案1
分组：development；难度：hard；场景组：family-39

## 销售原话
给销售做一个含税金额多报价刷新演示，标价已含税要拆开显示，需要审批后让客户确认。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：含税金额多报基础包，单价206.95元；B：含税金额多报扩展包，单价106.50元；C：含税金额多报专业包，单价247.99元。
- pricing：目录单价已含6%税；未税小计=含税金额/(1+税率)，小计先四舍五入到两位，税为含税金额减已显示小计；总价保持含税金额，不重复加税。
- workflow：报价记录及审批在刷新后保留；每次有效变更使旧审批失效，重新提交后才可批准。Q1/Q2各自的金额、审批、修订和历史在刷新后保留，刷新选回Q1、销售seller1。
- shipping：需要配送：自提pickup为0元，普通standard为12元，加急express为35元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-191/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-191.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计195.24、优惠0.00、税11.71、合计206.95、赠品0
- 5件A：小计976.18、优惠0.00、税58.57、合计1034.75、赠品0
- 11件A：小计2147.59、优惠0.00、税128.86、合计2276.45、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/tax-inclusive-accounting

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
