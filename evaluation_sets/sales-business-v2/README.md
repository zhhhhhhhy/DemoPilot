# Full-fixture business regression v2

This three-case revision was authored after the 2026-10-16 frozen intent A/B
audit. It preserves v1 fixtures/results and does not replace that A/B score.
The Core gets clarified business goals and the same hidden-assertion harness,
with 9 quote, 4 lead and 11 procurement journeys before publication.

Interventions include both clearer requirements and broader checks. A successful
rerun demonstrates targeted recovery under these requirements, not an isolated
effect of intent recognition, a randomized comparison or unseen generalization.

- Quote: explicitly display subtotal/discount and test both plans at 1/3/4/7 seats.
- Leads: explicitly adopt a global follow-up history and test both leads with
  both owners, including context switching. The old intent output filtered its
  task list by current lead; it retained data in memory. That audit failure alone
  did not prove data loss. This revision removes the presentation ambiguity.
- Procurement: provide three supplier facts, require a native selectable
  supplier control with an observable result, and cover all entity/owner pairs,
  ordering, missing reasons, rejection, terminal locks and reset.

Only the real Codex CLI Core edits generated card files. The driver and root
assistant edit the framework, requirements and authored tests. Independent
scoring is frozen in advance and gives no feedback after final publication.

Run `scripts/run_business_gate_regression.py --freeze/--real/--audit-only` with a
new output directory. `materialize_business_gates.py` refuses to overwrite an
existing versioned fixture directory.
