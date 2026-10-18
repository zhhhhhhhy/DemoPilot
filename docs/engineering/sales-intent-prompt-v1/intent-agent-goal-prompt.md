# Sales Intent Goal Prompt v1

## Purpose

Measure whether understanding a sales request before Core Builder generation improves the final DemoPilot result or reduces repair work. The experiment has two arms:

- **Control:** raw sales brief → the same Core Builder → the same browser and publication gates.
- **Treatment:** raw sales brief → Sales Intent Compiler → the same Core Builder → the same browser and publication gates.

The only intended difference is the additional intent step. The model, Core prompt, test data, maximum iterations, browser, and publication rules must stay the same.

## Prompt sent to the intent agent

```text
You are DemoPilot's Sales Intent Compiler.

Context files (read-only metadata; the runner supplies the contents needed for this turn):
- Repository root: <repo_root>
- Case index: evaluation_sets/sales-intent-v1/cases.json
- Case id: <case_id>
- Raw sales brief: <raw_sales_brief>
- Difficulty: <difficulty>
- Local input data: testdata/<case_id>/inputs.json
- Local asset directory: testdata/<case_id>/assets/
- Output evidence: artifacts/intent/<case_id>/intent.json
- Evaluator-only gold: evaluation_sets/sales-intent-v1/gold/intent-gold.json (not available to you)

Goal:
Compile the sales brief into an executable and testable typed intent for Core Builder. Preserve what the salesperson actually said. Do not fill gaps with plausible product ideas.

Rules:
1. Use only facts explicitly present in the raw sales brief.
2. Each must-have is one observable business capability and keeps the key phrase from the brief.
3. Do not invent features, discounts, pricing rules, roles, data, integrations, or production behavior.
4. Put uncertainty in assumptions/questions. If an unresolved question could change the Demo, set status to needs_clarification.
5. flow_steps contains only the explicitly stated business order.
6. acceptance_criteria describes visible user results, not implementation details.
7. The local input file is context for available demo fixtures; it is not permission to invent customer requirements.

Return exactly one JSON object with:
schema_version, status, case_id, actor, problem, desired_outcome,
must_haves, flow_steps, acceptance_criteria, constraints, non_goals,
assumptions, questions, confidence, traceability.

Before returning, check that every must-have has a source_quote, no capability was invented, the flow is ordered, and unresolved questions are visible.
```

## What counts as success

The trusted evaluator reads the hidden gold separately and reports three groups of numbers:

1. **Intent quality:** match by canonical requirement id or approved alias, not exact wording; report required-item precision/recall, flow coverage/order, unsupported invented items, and constraint violations.
2. **Final result:** published only when the hidden business check, fresh browser check, and no-constraint-violation check all pass.
3. **Work required:** first-pass rate, average repairs, total repairs, CLI calls, and elapsed time.

The intent score is diagnostic. It must not be used to remove failed treatment cases from the final-result denominator. A treatment case that fails intent extraction counts as a failed end-to-end case and does not start Core Builder.

## Files and information boundaries

- The intent agent receives the raw brief and the read-only input-data location.
- The intent agent and Core Builder never receive `gold/intent-gold.json`.
- For a causal final experiment, Builder should receive a `builder_contract.json` containing controls, actions, and input values without hidden expected-result text. The authoritative `acceptance.json` remains harness-only. If the current visible acceptance contract is used, report the result as an engineering release pilot, not causal proof that intent improved accuracy.
- Both arms write only their run-scoped card, card-web, and case testdata directories.
- The runner stores the intent prompt/context, intent output, intent score, Core request, revision count, browser result, and fresh post-publication audit.

## Decision rule

Claim that intent helps only if the treatment has a higher paired final-pass rate or a lower repair count on the same cases, with the difference reported by difficulty. Otherwise report “no measured improvement” and keep the intent failure or evaluation limitation visible.
