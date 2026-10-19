# sales-v3-159 买赠取消后修订·方案4
分组：development；难度：hard；场景组：family-32

## 销售原话
给销售做一个买赠取消后修订演示，买商品会送赠品，需要审批后让客户确认。三款演示商品为A：买赠取消后修基础包，单价206.95元；B：买赠取消后修扩展包，单价114.50元；C：买赠取消后修专业包，单价242.99元。商品A每购买6件另赠2件；输入数量是付费件数，赠品不收费，免费数量单独显示，不从付费数量扣减。取消后允许销售修订重提；每次有效变更使旧审批失效，重新提交后才可批准。需要配送：自提pickup为0元，普通standard为21元，加急express为50元，整单折扣税费后只加一次，切换方式也使审批失效。仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：买赠取消后修基础包，单价206.95元；B：买赠取消后修扩展包，单价114.50元；C：买赠取消后修专业包，单价242.99元。
- pricing：商品A每购买6件另赠2件；输入数量是付费件数，赠品不收费，免费数量单独显示，不从付费数量扣减。
- workflow：取消后允许销售修订重提；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：需要配送：自提pickup为0元，普通standard为21元，加急express为50元，整单折扣税费后只加一次，切换方式也使审批失效。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-159/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-159.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计206.95、优惠0.00、税0.00、合计206.95、赠品0
- 5件A：小计1034.75、优惠0.00、税0.00、合计1034.75、赠品0
- 11件A：小计2276.45、优惠0.00、税0.00、合计2276.45、赠品2

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/setting-up-buy-1-get-1-free-pricing-rule

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
