# Sales intent pilot v1

This pilot uses three authored sales cases already present in `codex-cli-v1`:

- `simple-quote-generator-01`
- `medium-lead-followup-01`
- `hard-procurement-approval-01`

Each case has one raw sales brief, a runner-only frozen seller-answer script under
`sales-clarifications/`, and an evaluator-only `gold/intent-gold.json`. The
current true-interview experiment is run by
`scripts/run_sales_intent_paired_real.py`; the answer scripts are deliberately
outside `testdata` so the Core workspace cannot read them before the intent
agent asks a matching question.

The true experiment compares two downstream inputs while holding Codex CLI, Core
Builder, common fixture data, browser contract, revision budget and publication
gates constant:

1. `raw-sales`: the raw brief is sent with no structured intent fields.
2. `intent-agent`: the same brief first goes to the intent agent. The runner
   releases the scripted salesperson answer only after the agent asks for the
   required topic; the resulting structured intent is then sent to Core.

The experiment is a release-behavior comparison, not a population-level causal
claim. It records interview questions, answer release, Core revisions, CLI
transcripts, terminal publication and independent browser audit separately.
`gold/intent-gold.json` is not copied to the Core workspace. Final reporting
must separate interview-gate failures, Core/build failures, browser/business-
contract correctness, and publication reliability.

The existing v1 acceptance contract remains the common engineering gate. Its
browser assertions prove visible interaction behavior; they do not prove real
OCR, inventory, CRM or procurement-system truth.
