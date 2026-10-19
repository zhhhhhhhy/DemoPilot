# Confirmed quotation application interface

Implement the exact catalogue, pricing profile(s), workflow and optional shipping in JSON. Profile keys and product IDs are selector values; display friendly Chinese labels and the confirmed product names. There are no other discounts or taxes. Prices use full precision then independent half-up two-decimal display rounding. Tax-inclusive subtotal is rounded before residual tax. Quantity tiers apply to all paid units, not progressive bands. Free units do not add charged units.

Required interface:
- selects #profile (only JSON profiles), #product/#second-product (A/B/C), #customer (standard/vip/partner), #record (Q1/Q2), #role (seller/manager/finance/customer), #actor (seller1/manager1/manager2/finance1/client1/intruder).
- inputs #quantity initially1, #second-quantity initially0, #date initially2026-03-15, #reason initiallyempty, #today initially2026-03-15 (simulated current day, separate from quote date).
- Initial profile is the FIRST declared JSON profile; productA, second-productB, customerstandard, recordQ1, roleseller, actorseller1. All amounts reflect initial values; stateDraft, revision0, approved-revision -1, history-count0.
- buttons #calculate, #submit, #approve, #reject, #accept, #cancel, #amend. Wrong/repeated/out-of-order actions preserve all committed values and history, showing #error; disabled actions are acceptable. No external submission.
- visible outputs #subtotal, #discount, #tax, #total with EXACT two-decimal money strings and no currency symbols; #free-quantity, #revision, #approved-revision, #history-count integer strings; #state uses exact codes Draft/PendingManager/PendingFinance/Approved/Rejected/Accepted/Cancelled.
- If contract version2, #shipping select pickup/standard/express initiallypickup and output #freight. Use confirmed charges, once per quote AFTER discounts and tax, include in approval threshold. Otherwise do not add shipping requirements. manual_override alone adds #manual-rate input initiallyempty.

Shared state rules:
Two independently stored quotes Q1/Q2; form changes are STAGED until Calculate. Switching record restores that quote. Product/quantity/customer/profile/date/manual-rate/shipping changes commit only via Calculate by seller; quantity integers, first>=1/second>=0; invalid or wrong-role commits change nothing. A genuinely changed quote increments revision AND history once, resets Draft, clears all approval, approved-revision=-1. Same-value recalculation does not accumulate discounts or history. Editing Accepted/Cancelled is forbidden.
Seller Submit from Draft/Rejected ->PendingManager, history+1, clears approvals. Manager Approve PendingManager ->Approved (or workflow's next step); finance cannot substitute for manager. Final approval sets approved-revision=current revision. Manager Reject PendingManager or finance Reject PendingFinance ->Rejected, clears approvals; history+1. Customer Accept only Approved ->Accepted. Seller Cancel except Accepted/Cancelled ->Cancelled and clears approvals. Each successful state transition including a partial manager approval adds exactly1 history; rejection/duplicate actions add0. Same manager actor cannot approve twice. Role/actor/reason/today/selected-record changes alone never alter quote history.

Selected workflow only:
single_manager: shared manager flow.
two_stage: manager ->PendingFinance, finance ->Approved.
threshold: after manager, total>=approval_threshold ->PendingFinance elseApproved.
dual_manager: manager1 first remainsPendingManager; repeating manager1 denied; manager2 completesApproved.
rejection_reason: Reject requires a nonempty trimmed reason; fixing/resubmitting clears approvals.
cancel_amend: seller Amend fromCancelled ->Draft, revision+1/history+1, retain fields and clear approvals.
customer_owner: Accept requires customer role AND client1 actor; intruder denied.
expiry: Accept requires today<=valid_until, including boundary; changing today alone does not mutate quote.
record_persistence: persist each quote's fields, amounts, state, revisions, history, approvers across reload; reload resets selected record/role/actor toQ1/seller/seller1. Other workflows need in-page isolation; persistence optional.
manual_override: positive manual-rate replaces A unit rate before pricing and persists on later recalculation; configured customer protocol rate takes precedence for rate_override; nonpositive manual rate invalid.

Pricing details are in JSON. For rate_override, Subtotal uses original catalogue/manual prices, the rate difference appears in Discount. Do not change confirmed prices or business rules to satisfy a test. Use only local files, no remote requests. Keep scripts in app.js, styles in styles.css, no inline event handlers. The parent owns trusted tests and publishing; implement and self-test until those checks pass or report the unmet goal.
