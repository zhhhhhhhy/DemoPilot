# Public source provenance

The machine-readable source registry is [sources.json](../sources.json). It was checked against live official documentation on 2026-10-16. It covers ten rule families using four documents; the documents are not treated as ten independent customer requests.

| Source | Supported family IDs |
| --- | --- |
| [Pricing Rule](https://docs.frappe.io/erpnext/pricing-rule) | `quantity_threshold`, `customer_scope`, `overlap_priority`, `discount_composition`, `mixed_item_threshold`, `rate_override`, `rule_validity` |
| [Applying a Discount](https://docs.frappe.io/erpnext/applying-discount) | `fixed_net_discount` |
| [Buy One Get One Free](https://docs.frappe.io/erpnext/setting-up-buy-1-get-1-free-pricing-rule) | `free_item` |
| [Tax Inclusive Accounting](https://docs.frappe.io/erpnext/tax-inclusive-accounting) | `tax_inclusive` |

These sources justify the business-rule families. Fixture companies, amounts, thresholds, dates and scripted seller responses are authored synthetic configurations. They must be labelled as documentation-derived requirements, never real customer interviews or operational data.

Before any scoring run, freeze the complete synthetic configuration and numerical oracle. Each requirement must distinguish the source-supported rule from added benchmark choices. In particular, explicitly define named priority order, promotion-date boundaries, discount allocation, gift repetition, rounding and the evaluation date. The registry lists the unresolved product-specific details.

The final family split is four development families (`quantity_threshold`, `customer_scope`, `rule_validity`, `discount_composition`) and six held-out families (`overlap_priority`, `mixed_item_threshold`, `rate_override`, `tax_inclusive`, `fixed_net_discount`, `free_item`). The split is a benchmark design choice. In the gift case, repeated floor-based buy-two-get-one behavior is explicitly configured by the synthetic seller; the source establishes the promotion family, not that default repetition algorithm.

Keep development tasks separate from sealed test tasks. Do not use a sealed-task failure to change a prompt, scorer or requirement and then continue to call the result a first-pass holdout measurement. If a protocol defect makes a test invalid, preserve the attempt and label a replacement explicitly.

Public documentation is a credible source for verifiable calculation rules. It does not establish product demand, usability, time saved, sales conversion or real-user acceptance.
