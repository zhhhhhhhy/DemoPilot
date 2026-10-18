# Historical v3: clarified-text structure experiment

> **Validity boundary:** This is not the true sales-interview A/B experiment requested later. Both arms received the same already-clarified sales description. Keep this report as engineering evidence only; do not use its `1/3` versus `2/3` as proof that asking the salesperson improved the final result. The corrected protocol is [true-intent-ab-protocol-2026-10-08.md](true-intent-ab-protocol-2026-10-08.md).

## Scope

This run tests the narrower question: does a real typed-intent step improve the downstream Core Builder result when both arms already receive the same clarified sales description? Each of the three authored cases was run twice with the same `gpt-6.1-sol` model, fixtures, hidden expected results, Core prompt, browser gates, and a two-round Core revision budget.

- `raw-sales`: the clarified sales description went directly to Core.
- `intent-agent`: the same description first went through the real Codex CLI intent step; Core received its typed intent only when the trusted delivery gate passed.

The intent step did not receive evaluator-only gold answers. The independent audit was frozen before the run, used local Playwright Chromium with a fresh context per journey, and did not send repair feedback to Core.

## Aggregate result

| Arm | Final published and independently audited | Core revision rounds | CLI calls | First-pass final cases |
| --- | ---: | ---: | ---: | ---: |
| raw-sales | 1/3 | 4 | 14 | 1/3 |
| intent-agent | 2/3 | 1 | 9 (3 intent calls) | 1/3 |

The observed paired difference is one additional final pass, three fewer Core revision rounds, and five fewer total CLI calls for `intent-agent`. This is an observed three-case engineering pilot, not a causal or population-level accuracy estimate for a salesperson-interview module.

## Case-level result

| Case | raw-sales | intent-agent | Failure boundary |
| --- | --- | --- | --- |
| `simple-quote-generator-01` | Published; browser and fresh post-publish audit passed; 0 revisions | Published; browser and fresh post-publish audit passed; 0 revisions | No product failure in v3 |
| `medium-lead-followup-01` | Hidden after 2 revisions and 6 CLI calls | Published after 1 revision and 5 CLI calls; independent audit passed | Raw first attempt had a real Core defect: the filtered lead did not create the required `待跟进` task. The repair then lacked verifiable acceptance-child evidence because the Windows command/TLS transport failed; release stayed hidden. |
| `hard-procurement-approval-01` | Hidden after 2 revisions and 6 CLI calls | Hidden before Core; 1 intent call | Both are Codex CLI workspace-routing failures. The intent arm never reached Core; the raw arm produced no usable card and no acceptance evidence. |

The external audit found no published defect among published rows. Its strict business result was raw `1/3`, intent `2/3`; unpublished cases remained in the denominator and were not counted as passes.

## Before/after repair evidence

The first v2 run stopped on the first raw case because Core repeatedly wrote `work/WORKFLOW_STATE.json` and `.md` outside its allowed `card/`, `card-web/`, and case `testdata/` roots. The Goal Prompt was strengthened to forbid those workflow files. In v3 the simple case passed in both arms on the first Core attempt with zero unauthorized-path findings, showing that this prompt repair removed the known permission blocker. It does not by itself prove intent quality.

## Measurement boundary

The first external audit attempt was invalid because the local API on port 8091 was stopped and Chromium received `ERR_CONNECTION_REFUSED`. The API was restarted, the same frozen audit protocol was rerun without changing any build result, and the second audit completed with fresh browser contexts. The six run directories retain Core prompts, CLI JSONL, stderr, acceptance-child traces, browser screenshots, and terminal states.

The three cases use the same clarified sales descriptions in both arms. Therefore this run measures whether structured intent organization helps downstream generation; it does not measure a customer-facing clarification interview, information acquisition, or intent-recognition accuracy against an unseen gold set. For the latter question, use the corrected protocol in `true-intent-ab-protocol-2026-10-08.md`.
