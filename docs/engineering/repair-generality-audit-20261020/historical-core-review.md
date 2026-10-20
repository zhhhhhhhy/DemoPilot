# Historical Core repair generality audit

- Transaction: `TX-dc0a599ec621`; parent attempt `A-001`.
- Worker: `historical_core_audit`; bounded attempt `HIST-001`.
- Mode: read-only source, Git and historical evidence audit. No product/data/test-standard changes; no CLI/model/browser runs; no unexecuted final-85 case content opened.
- Scope: early Core changes in `1af6b33 -> fc23a81`, follow-on quotation integration `fc23a81 -> 2124ac4`, plus current implementations of the same Core/quotation gates and historical reliability records.
- Outcome: completed with substantiated limits. The inspected production paths contain no observed case-ID/answer-specific success bypass. Several real repairs are general mechanisms. Existing evidence is nevertheless narrower than a broad business-generalization claim, and two concrete acceptance gaps are visible in source.

## 1. Repair-by-repair classifications

| Historical change | Code/Git evidence | Classification and limit |
|---|---|---|
| Replace runtime fetch / inline fixture scripts with an offline JavaScript fixture constant, DOM APIs, and preservation of already passing behavior | `git diff fc23a81^ fc23a81 -- backend/src/demopilot/core_loop.py`; current `core_loop.py:160-177`. Historical failure loop and action: `docs/engineering/failure-analysis-2026-10-07.md:41-86`. | General implementation guidance for every task under the declared offline static-app contract. It does not contain the failed task's answer, status text or a case-specific success branch. This demonstrates repair of an under-specified execution constraint; it does not establish a new general reasoning capability. |
| Pin acceptance child to the project interpreter with `-S`; include stdout/stderr EOF in the CLI timeout and give stream readers one owner | Same commit's `core_loop.py` child prompt/agent definition and `providers/codex_cli.py` diff. Current `core_loop.py:184-201,253-257`; `providers/codex_cli.py:465-478`. Failure follow-up: `failure-analysis-2026-10-07.md:100-108`. | General environment/process-lifecycle repair. Independent of business case ID or expected business output. Historical 20/20 is explicitly incremental recovery, not a fresh full rerun. |
| Stage hidden candidate and require fresh Chromium audit before publication; quotation release binds job, requirement revision, check and exact artifact bytes | `fc23a81` adds the candidate audit; current `core_loop.py:470-518,538-635`; `quotation_release.py:108-164,166-220`. | General fail-closed reliability mechanism. No case-ID whitelist found in these inspected paths. The candidate audit is an independent execution/context, not an independently authored acceptance specification. |
| Add customer-price subtotal semantics, pricing boundaries, reload semantics and later parameterize boundary vectors / initial profile | `docs/quotation-reliability-v2/失败与改进记录.md:8-11`; `protocol-corrections.json`; `git diff fc23a81 2124ac4 -- backend/src/demopilot/quotation_contract.py` adds `next(iter(contract['profiles']))` and `contract.get('boundary_vectors', {}).get(profile, edge_values)`. Current `quotation_contract.py:127-129,370-416`. | Domain-level contract and checker correction, not task-ID answer bypass. It is narrower than infrastructure repair: the supported pricing/workflow vocabulary, UI protocol and defaults are a fixed family. The added generic configuration hook helps reuse but does not itself prove transfer to new rule semantics. |

The scoped search for `case_id ==`, `evaluation_case_id ==`, case-ID membership, `sales-v3-`, `qflow-`, `simple-`, `medium-`, and `hard-` in the listed Core/quotation production modules returned no matches (rg exit 1). This is evidence about the inspected files, not a proof that the entire repository or all historical outputs are free of benchmark-specific logic. Dataset materializers naturally contain case IDs and authored expected outputs; those are not release bypasses.

## 2. Where engineering coverage is incomplete

### 2.1 Fresh execution is stronger isolation, but the expected-result definition is shared

Old Core runs the same `run_acceptance` primitive on a copied candidate (`core_loop.py:591-599`; `core_acceptance.py:123-128`). It protects against stale workspace/browser state and self-reported success. It cannot expose a requirement that was omitted from that same authored contract.

Quotation public tests and private tests both use the same `QuoteModel` and `journeys` implementation:

- `scripts/materialize_quotation_reliability.py:43-44` compiles both public and private fixtures.
- `quotation_contract.py:247-257` changes a small set of input values for private paths; `415-416` reverses existing boundary vector order.
- `quotation_contract.py:459-469` computes expected snapshots with the same model for either mode.
- `quotation_browser.py:20,164-165,207` imports that model/path generator in the actual Chromium runner.
- `scripts/run_quotation_reliability.py:176-202,229-237` does wait for terminal outcomes, runs `private=True` on frozen terminal candidates, and records no feedback to Builder. That is a real useful separation and must be credited.

**Consequence:** the paths really executed and passed; shared expected-result logic does not invalidate those observations or imply cheating. However, a missing assertion, missing rule or reference-model misunderstanding can be reproduced by both public and final checks. An additional independently specified business example/alternate reference calculation and contract-to-assertion traceability are needed before claiming broader semantic coverage. The repository already has hand-calculated rule examples and controlled checker mutations; they are partial mitigations, not a complete independent specification.

### 2.2 Concrete missing assertion: restoration of record form inputs

The authored common contract says that switching record restores that record's committed values, and persistence restores input values (`scripts/materialize_quotation_reliability.py:63-70,82`).

Actual visible snapshots include price, state, revision, approved revision and history count, but exclude form values (`quotation_contract.py:139-147`; `quotation_browser.py:91-101,114-137`). Before calculate, the test driver reads the form then writes **all** fields back to the reference record's expected values (`quotation_browser.py:221-246`).

**Static finding:** an app can display correct record totals/state while leaving a stale quantity/product/date in the form after switching records; this specific user-visible requirement is not directly asserted, and the driver may overwrite the bad form before the next calculation. The current audit therefore does not prove form restoration merely because its record-isolation price/state checks pass. This audit has not injected that defect or executed a browser, so it does not assert that any already generated page actually has this defect.

### 2.3 Concrete missing assertion: user-visible explanation for rejected action

The authored UI contract requires `#error` to explain rejected actions (`materialize_quotation_reliability.py:66`). `quotation_browser.py:91-101` has no error output in its asserted field map; `_assert_snapshot` only reads mapped outputs (`114-137`). `accepted` is a reference-model variable written into the trace (`247-265`), not an observation that the app showed an error.

**Static finding:** a rejected action that silently does nothing may satisfy all asserted price/state/counter checks. Correct rejection preservation is measured; completeness of the explanatory message is not. Again, this is an acceptance coverage gap, not a demonstrated defect in the existing generated pages.

## 3. Template generality and effective sample size

### Quotation reliability v2

`materialize_quotation_reliability.py:23-48` derives all ten price profiles from the earlier quotation set, reuses one catalogue, and takes a 10 workflow x 10 pricing cross-product. The split is by workflow app: first three development, seven held out (`45,50`). It is not 100 independently sourced customer requirements, nor a holdout of unfamiliar pricing families.

The protocol intentionally fixes A/B/C, two records, simulated roles, dates, output IDs and transition codes (`58-87`). Those constants are functional interface/domain definitions, not evidence of case-ID hardcoded passing. But success on this family cannot demonstrate arbitrary workflow generation, production authorization, live ERP integration or unseen business-rule semantics. `docs/quotation-reliability-v2/结果与贡献.md:13-15,28-30,43,49,58` already discloses most of those boundaries.

### Earlier hard-v2

`scripts/materialize_hard_eval_v2.py:148-173` gives all eight tasks the same generic phase-N / branch / approve / terminal controls. `177-213` verifies phase-name/timeline strings, generic illegal terminal, one branch label prefix, and entity isolation. `243` supplies generic entity-01/02/03 and sub-01/02/03 fixtures.

The `threshold-or-role-branch` path clicks `#branch` and checks `case['branch'][:8]` (`199-204`); it does not construct paired business values on either side of the threshold or prove actual role-dependent behavior. The manifest nevertheless describes approval roles, derived aggregates and terminal locks (`270-279`). That is a concrete gap between narrated difficulty and the executable coverage. It demonstrates a multi-step UI/state template with some negative/isolation checks, not independently deep validation of eight business domains.

## 4. What should change in the process (not implemented by this audit)

1. Every historical repair record should identify the invariant being repaired and list a different development expression/parameter that must also work, plus a negative control. Replaying only the observed failure is regression protection, not generalization evidence.
2. Maintain a requirement-to-assertion coverage matrix: each mandatory visible behavior must map to a browser observation. Input restoration and rejection explanation must be checked directly; action drivers must not repair the product state before measuring that requirement.
3. Maintain separate descriptions for independent runtime, independent inputs and independently derived expected results. Use manually derived golden examples or a second implementation on a bounded cross-section to reduce common-mode oracle errors.
4. Freeze by business family and meaningful structural novelty, not just renamed IDs, shuffled values or repeated combinations. Report independent applications, independent requirements, combinations and repeated path executions separately.
5. Keep old scores immutable. Do not fix final-case-derived aliases/templates and count the same final cohort as a fresh generalization test. New repairs use development-only data, then a new freeze and an unopened cohort.

## 5. Evidence limits and attempt record

- The historical `fc23a81` commit bundles many changes and evidence documents. Git establishes what was committed relative to its parent; it does not independently timestamp each local pre-freeze intervention. The historical hash/protocol records provide additional provenance but were not treated as stronger evidence than inspected source.
- No claim of exhausting all historic commits/modules; scope and file evidence are listed above.
- No Codex invocation, API model, browser launch, hidden-final inspection, code fix, changed criterion or GitHub write occurred.
- Bounded attempt `HIST-001`: `completed`; produced this evidence file and sent findings to parent. Suggested fixes are unimplemented; current scored paths retain their original meaning.
