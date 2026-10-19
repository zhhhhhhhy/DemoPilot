# sales-v3-079 整单减免驳回修订·方案4
分组：heldout；难度：medium；场景组：family-16

## 销售原话
给销售做一个整单减免驳回修订演示，整单减钱再算税，需要审批后让客户确认。三款演示商品为A：整单减免驳回基础包，单价158.95元；B：整单减免驳回扩展包，单价98.50元；C：整单减免驳回专业包，单价210.99元。整单先减免24.50元，最多减到0；再对减免后金额加3%税，税四舍五入两位，不按减免前金额计税。驳回必须填写原因，修改后重新提交；每次有效变更使旧审批失效，重新提交后才可批准。不需要配送，没有额外运费。仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：整单减免驳回基础包，单价158.95元；B：整单减免驳回扩展包，单价98.50元；C：整单减免驳回专业包，单价210.99元。
- pricing：整单先减免24.50元，最多减到0；再对减免后金额加3%税，税四舍五入两位，不按减免前金额计税。
- workflow：驳回必须填写原因，修改后重新提交；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-079/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-079.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计158.95、优惠24.50、税4.03、合计138.48、赠品0
- 5件A：小计794.75、优惠24.50、税23.11、合计793.36、赠品0
- 11件A：小计1748.45、优惠24.50、税51.72、合计1775.67、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/applying-discount

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
