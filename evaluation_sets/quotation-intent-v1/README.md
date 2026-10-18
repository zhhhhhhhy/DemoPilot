# Quotation intent evaluation v1

Purpose: measure whether acquiring missing seller requirements improves the
business correctness of generated quotation demos, with the same Codex CLI Core.

This is a documentation-derived benchmark, not a collection of ten customers.
Four official ERPNext documents substantiate ten rule families. Product records,
prices, dates, rule precedence and seller preferences are synthetic and declared
before generation. There are no real sales interviews or commercial outcomes.

## Inputs and split

- Ten distinct pricing configurations, not ten variants of one price input.
- Development: quotation-01 to quotation-04.
- Held-out: quotation-05 to quotation-10. No generated held-out output may inform
  prompts, seller scripts, Core, scoring, thresholds or retry policy.
- Quotation-03 and quotation-07 state the full business rule initially. They
  check unnecessary questions when requirements are already sufficient.
- The other eight initial requests omit real configuration choices. Correctness
  means meeting the predeclared simulated seller preference, not guessing a
  universal default that the documentation does not establish.
- All records needed by demos are in project-root testdata/<case-id>/.
- inputs.json contains the same catalogue, customers and general engineering
  conventions for both arms. It contains no seller-specific pricing rules.
- Seller responses are outside testdata in seller-answers/. Specific topics are
  released only in response to matching questions. A clearly requested complete
  pricing policy may release all topics. Matching is a frozen keyword protocol,
  not a validation of nuanced human conversational understanding.
- private/ contains configured business rules and positive/negative vectors,
  available only to the trusted offline evaluator.

## Comparison and acceptance

A (direct): the initial business sentence plus common engineering requirements,
UI contract and ordinary fixtures, with no seller response.

B (clarify): the same sentence goes through the existing typed-intent agent
with a quotation-specific interview context. At most three CLI turns, with
answers supplied after relevant questions. Core receives typed intent and
verbatim released facts so text-field truncation cannot silently discard facts.

Both Core runs use gpt-6.1-sol, medium reasoning, 300 seconds per CLI call and
at most two Core repair rounds after initial generation. Two independent cases run concurrently; arms are sequential within a pair and order alternates by
case. One paired execution per task is planned; this does not characterize
model variance.

The common engineering gate tests operability and invalid input. Final business
correctness is NOT used for internal repair. After both arms finish, a separate
Decimal oracle and fresh local Chromium contexts check all 62 positive vectors,
30 invalid-input paths and 20 repeated/change-and-return paths across the ten
tasks, per arm: 112 journeys. Every monetary result and gift count is reread
from visible DOM. Invalid input must produce a visible error, preserve the last
valid quote and allow recovery. Hidden numbers, substring matches and final
model self-reports do not count.

Primary endpoint: every business journey passes and the original Core task
published. A task that never published stays in the denominator; its browser
journeys are not_run, not passed. Final scoring never triggers repair. All
generated source hashes are checked before and after scoring.

Experiment runs use a separate RunStore inside each result directory. An
engineering-published experimental artifact does not enter the product
dashboard. Published-but-wrong counts refer to this internal experiment.

## Evidence and interpretation

sources.json maps requirements to source documents; cases.json enumerates
tasks and paths; manifest.json hashes inputs, scripts and private acceptance.
The materializer refuses to replace changed dataset artifacts. Before the first
model call, independent review corrected tax wording, weak invalid-input checks,
unequal common context and overbroad answer release; design snapshots remain in
docs/quotation-intent-v1/. No generated result informed those changes.

Development and held-out result folders each freeze code/data/model settings
before execution. Reusing a result folder with different hashes is refused.
Failed runs, partial logs, native/fallback acceptance evidence, prompts, exact
intent stdin, question/answer turns, generated files and screenshots remain.

The held-out six-case comparison is primary. Development scores are diagnostic.
Journey counts cannot be treated as independent customers. Report observed pass
differences, costs and an exact paired-case diagnostic with the small-sample
boundary. This experiment measures the whole clarification-and-information
delivery method, including extra information and its cost. It does not isolate
prompt wording, prove intrinsic model improvement or measure seller satisfaction.

## Commands

Use the project's Python environment and run from D:/worker/DemoPilot.

    backend/.venv/Scripts/python.exe scripts/materialize_quotation_intent.py --write
    backend/.venv/Scripts/python.exe scripts/run_quotation_intent_ab.py --split development --output-dir evaluation_sets/quotation-intent-v1/results/development-v2-20261016 --freeze
    backend/.venv/Scripts/python.exe scripts/run_quotation_intent_ab.py --split development --output-dir evaluation_sets/quotation-intent-v1/results/development-v2-20261016 --real
    backend/.venv/Scripts/python.exe scripts/audit_quotation_intent.py --results-dir evaluation_sets/quotation-intent-v1/results/development-v2-20261016

After the development decision is recorded and implementation frozen, use the
same freeze/real/audit commands with split heldout and a distinct results path.
Never replace the original held-out score with a repaired result.

The earlier development-20261016 pilot stopped after four terminal arms to repair answer ambiguity and a live-update gate assumption. It remains preserved, is not the final four-case development comparison, and is never substituted for held-out evidence. Hidden numerical gold stayed unchanged.

Development-v2 completed all eight arms: independent business passes were direct 1/4 and clarify 3/4. The remaining clarification was ready but rejected solely for an empty explicit-order list, contradicting the compiler instruction not to invent order. The delivery validator was aligned with that instruction and the affected task passed a separate fresh 12/12-journey regression. Original development scores remain unchanged. The subsequent six-case held-out evaluation uses the final fixed code in its own frozen directory.
# 本轮结果入口

最新已追加C完整规则直输，共新增10个结果，与原20个分支分开留存。六题严格完整评分A1/6、B5/6、C5/6；功能检查36/68、67/68、68/68，C全十题112/112功能检查通过，但一条读取检查误报保留原分。见[三组归因与简历贡献](../../docs/quotation-information-ablation-v1/结果与简历贡献.md)。下方20个分支和旧指标指原两组，不代表尚未运行C。

全部计划20个分支均已记录终态。主结果只使用6条保留题：直接生成1/6、先询问5/6；独立浏览器检查36/68与67/68。报价08询问组的一条操作超时在原样诊断中通过，但保留首次评分；调用14→25，Core调用14→14，返工1→1，不作速度或成本改善结论。

[通俗结果与贡献](../../docs/quotation-intent-v1/结果与贡献.md) · [10条需求与验收](需求与验收.md) · [测量说明](../../docs/quotation-intent-v1/measurement-notes.md)。`results.json`里的`business_status=not_run`是生成阶段占位，最终业务成绩以各批`business-audit.json`为准；这两个阶段的原记录均保留。

