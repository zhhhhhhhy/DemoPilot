# sales-v3-139 手工单价及整单减免·方案4
分组：heldout；难度：medium；场景组：family-28

## 销售原话
给销售做一个手工单价及整单减免演示，整单减钱再算税，需要审批后让客户确认。三款演示商品为A：手工单价及整基础包，单价194.95元；B：手工单价及整扩展包，单价110.50元；C：手工单价及整专业包，单价234.99元。整单先减免24.50元，最多减到0；再对减免后金额加3%税，税四舍五入两位，不按减免前金额计税。允许销售调整商品 A 单价，修改后重新审批；每次有效变更使旧审批失效，重新提交后才可批准。销售可手工修改A单价，后续重算保留；非正数拒绝，修改必须重新审批。不需要配送，没有额外运费。仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：手工单价及整基础包，单价194.95元；B：手工单价及整扩展包，单价110.50元；C：手工单价及整专业包，单价234.99元。
- pricing：整单先减免24.50元，最多减到0；再对减免后金额加3%税，税四舍五入两位，不按减免前金额计税。
- workflow：允许销售调整商品 A 单价，修改后重新审批；每次有效变更使旧审批失效，重新提交后才可批准。销售可手工修改A单价，后续重算保留；非正数拒绝，修改必须重新审批。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-139/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-139.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计194.95、优惠24.50、税5.11、合计175.56、赠品0
- 5件A：小计974.75、优惠24.50、税28.51、合计978.76、赠品0
- 11件A：小计2144.45、优惠24.50、税63.60、合计2183.55、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/applying-discount
- https://www.odoo.com/documentation/17.0/applications/sales/sales/products_prices/prices/pricing.html

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
