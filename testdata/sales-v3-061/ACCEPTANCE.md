# sales-v3-061 批量价格驳回重提·方案1
分组：development；难度：medium；场景组：family-13

## 销售原话
给销售做一个批量价格驳回重提演示，买得多有优惠，需要审批后让客户确认。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：批量价格驳回基础包，单价128.95元；B：批量价格驳回扩展包，单价80.50元；C：批量价格驳回专业包，单价195.99元。
- pricing：仅商品A按数量优惠：满3件优惠7%，满8件优惠18%；命中最高优惠档，对该商品全部付费数量生效，不分段、不叠加，同商品两行合并数量。
- workflow：驳回必须填写原因，修改后重新提交；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-061/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-061.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计128.95、优惠0.00、税0.00、合计128.95、赠品0
- 5件A：小计644.75、优惠45.13、税0.00、合计599.62、赠品0
- 11件A：小计1418.45、优惠255.32、税0.00、合计1163.13、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
