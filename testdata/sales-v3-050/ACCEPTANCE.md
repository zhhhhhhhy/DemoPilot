# sales-v3-050 促销赠品报价·方案5
分组：development；难度：simple；场景组：family-10

## 销售原话
给销售做一个促销赠品报价演示，买商品会送赠品，需要审批后让客户确认。细节要问我，不能自行选默认价格或忽略边界。经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。

## 完整业务规则（只在实际问到时回答）
- catalogue：三款演示商品为A：促销赠品报价基础包，单价147.95元；B：促销赠品报价扩展包，单价97.50元；C：促销赠品报价专业包，单价201.99元。
- pricing：商品B每购买7件另赠1件；输入数量是付费件数，赠品不收费，免费数量单独显示，不从付费数量扣减。
- workflow：经理审批后由客户确认；每次有效变更使旧审批失效，重新提交后才可批准。
- shipping：不需要配送，没有额外运费。
仅本地离线演示，无其他税费或优惠；数量为整数，所有金额采用十进制计算、独立四舍五入两位，不用显示出来的舍入差额反算总价。

## 功能验收
- primary：Confirmed semantic plan matches seller facts, publishes within budget, all mandatory final independent journeys pass, accepted source unchanged.
- monetary：Exact per-step subtotal, discount, tax, total and gift quantity; cent equality, no tolerance.
- workflow：Correct actor/order, duplicate/invalid actions preserve committed values/history, edits invalidate approval, records isolated.
- publish：No user confirmation or failed/cancelled/stale job => no publication; exact accepted artifact bytes only.
- public：testdata/sales-v3-050/public-tests.json
- private：evaluation_sets/sales-benchmark-v3/private/sales-v3-050.json
- scoring：Every mandatory journey must pass. Intermediate Core repair is not final failure. Unpublished or wrong final output fails full delivery.

## 可直接核对的金额
- 1件A：小计147.95、优惠0.00、税0.00、合计147.95、赠品0
- 5件A：小计739.75、优惠0.00、税0.00、合计739.75、赠品0
- 11件A：小计1627.45、优惠0.00、税0.00、合计1627.45、赠品0

## 来源
- https://docs.frappe.io/erpnext/pricing-rule
- https://docs.frappe.io/erpnext/workflows
- https://docs.frappe.io/erpnext/quotation
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-prices-and-discounts
- https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- https://docs.frappe.io/erpnext/setting-up-buy-1-get-1-free-pricing-rule

合成规则，不是真实客户记录。公开逐步期望见public-tests.json，独立计划只供最终评分。
