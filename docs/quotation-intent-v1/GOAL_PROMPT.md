# Complete the quotation intent comparison

## Purpose

Establish an honest, reproducible account of the user's contribution to DemoPilot:
does obtaining missing quotation requirements improve the delivered demo compared
with sending the original sentence directly to the same Codex CLI Core?

## Context

Project root: D:/worker/DemoPilot.
Current transaction: docs/quotation-intent-v1/WORKFLOW_STATE.json, TX-b059e0b20f36.
Requirements: evaluation_sets/quotation-intent-v1/cases.json and 需求与验收.md.
Primary source registry: evaluation_sets/quotation-intent-v1/sources.json.
Ordinary demo inputs: testdata/quotation-01 through testdata/quotation-10.
Frozen synthetic seller scripts and private business configurations remain in
evaluation_sets/quotation-intent-v1/seller-answers and private, outside Core.

The original development-20261016 pilot stopped after four terminal arms because
of answer ambiguity and an incorrect live-update assertion. Preserve it.
Current development: results/development-v2-20261016. After all eight arms and
their offline audit, record a development decision and freeze heldout-20261016.

## Outcome

Complete ten documentation-derived independent pricing configurations: four
development tasks and six held-out tasks. Both arms use the same ordinary
fixtures, engineering contract, gpt-6.1-sol/medium Core, 300-second CLI deadline
and two Core repair rounds. At most two independent cases run concurrently,
with sequential, alternating arm order inside each pair. Clarification has at
most three 120-second typed-intent calls; charge their time and calls.

The two initially sufficient tasks are quotation-03 and quotation-07. Do not
force them to ask questions or penalize ready output just for skipping questions.
Release only requested seller topics; preserve source facts in the Builder input.

Run the full offline business oracle only after each evaluation group terminates.
The six held-out results may never inform code, prompts, answers, budgets, gold
or thresholds. Never repair generated pages manually or substitute a repaired
run for a scored result. Internal Core repair is allowed and recorded separately
from final task failure.

## Assessment

Primary comparison is six held-out task outcomes. A pass requires original
delivery plus all required positive, invalid-input, repeated-calculation and
change-and-return journeys. Across all ten tasks there are 112 journeys per arm.
Unpublished and unverified results remain in the planned denominator.

Use real local Playwright Chromium, fresh contexts, visible exact numeric
outputs, no external network, original source hashes before/after, page-error
checks, question/answer records and retained CLI stdin/stdout/stderr.
No product dashboard publication of unverified experimental artifacts.

Report measured pass counts, published-but-wrong cases, first pass, Core repair,
all observed outer CLI calls and end-to-end elapsed time. Keep development and
test scores separate. Explain that public rule provenance is not real sales
feedback, extra seller information is part of the intervention, native child
cost may be partially observed, and six tasks/single executions do not prove a
population-wide or commercial benefit.

Final deliverables:
- docs/quotation-intent-v1/结果与贡献.md and metrics.json;
- evidence-backed resume/interview wording and links from portfolio materials;
- append-only problem -> action -> result entries in docs/ITERATION_METHODS.md;
- all acceptance criteria evidenced, task-owned processes cleaned up.

Finish the authorized work autonomously. Final Chinese report must say plainly
what the user contributed and whether the experiment actually improved results.
Do not replace the outcome with a list of engineering housekeeping steps.
