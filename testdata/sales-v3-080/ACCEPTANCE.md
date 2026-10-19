# sales-v3-080 整单减免驳回修订·方案5
分组：heldout；难度：medium；场景组：family-16

## 销售原话
给销售做一个整单减免驳回修订演示，整单减钱再算税，需要审批后让客户确认。细节要问我，不能自行选默认价格或忽略边界。驳回必须填写原因，修改后重新提交；每次有效变更使旧审批失效，重新提交后才可批准。还需要演示配送计费。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：整单减免驳回基础包，单价165.95元；B：整单减免驳回扩展包，单价103.50元；C：整单减免驳回专业包，单价213.99元。
- pricing：整单先减免28.50元，最多减到0；再对减免后金额加7.5%税，税四舍五入两位，不按减免前金额计税。
- workflow：驳回必须填写原因，修改后重新提交；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：需要配送：自提pickup为0元，普通standard为24元，加急express为55元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-080/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-080.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计165.95、优惠28.50、税10.31、合计147.76、赠品0
- 5件A：小计829.75、优惠28.50、税60.09、合计861.34、赠品0
- 11件A：小计1825.45、优惠28.50、税134.77、合计1931.72、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/applying-discount

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
