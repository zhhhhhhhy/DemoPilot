# sales-v3-100 价内税两级审批·方案5
分组：heldout；难度：medium；场景组：family-20

## 销售原话
给销售做一个价内税两级审批演示，标价已含税要拆开显示，需要审批后让客户确认。细节要问我，不能自行选默认价格或忽略边界。经理、财务依次审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：价内税两级审基础包，单价177.95元；B：价内税两级审扩展包，单价107.50元；C：价内税两级审专业包，单价221.99元。
- pricing：目录单价已含7.5%税；未税小计=含税金额/(1+税率)，小计先四舍五入到两位，税为含税金额减已显示小计；总价保持含税金额，不重复加税。
- workflow：经理、财务依次审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：需要配送：自提pickup为0元，普通standard为24元，加急express为55元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-100/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-100.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计165.53、优惠0.00、税12.42、合计177.95、赠品0
- 5件A：小计827.67、优惠0.00、税62.08、合计889.75、赠品0
- 11件A：小计1820.88、优惠0.00、税136.57、合计1957.45、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/tax-inclusive-accounting

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
