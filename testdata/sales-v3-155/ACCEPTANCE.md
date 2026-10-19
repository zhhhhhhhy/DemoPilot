# sales-v3-155 连续折扣异人会签·方案5
分组：heldout；难度：hard；场景组：family-31

## 销售原话
给销售做一个连续折扣异人会签演示，优惠要先后计算，需要审批后让客户确认。细节要问我，不能自行选默认价格或忽略边界。两位不同经理会签后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：连续折扣异人基础包，单价210.95元；B：连续折扣异人扩展包，单价118.50元；C：连续折扣异人专业包，单价243.99元。
- pricing：全部商品整单依次优惠12%再优惠5%，每次基于上次优惠后的金额，禁止直接把百分比相加。
- workflow：两位不同经理会签后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：需要配送：自提pickup为0元，普通standard为24元，加急express为55元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-155/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-155.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计210.95、优惠34.60、税0.00、合计176.35、赠品0
- 5件A：小计1054.75、优惠172.98、税0.00、合计881.77、赠品0
- 11件A：小计2320.45、优惠380.55、税0.00、合计1939.90、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
