# DemoPilot Codex CLI Agent Core Evaluation Set v1

This set evaluates whether the local `codex_cli` provider can turn a structured
intent into a runnable, reviewable static Demo. It is an Agent Core generation
benchmark, not a production integration or an OCR accuracy benchmark.

## Size and difficulty

| tier | cases | flow rule |
| --- | ---: | --- |
| simple | 10 | 1–2 business phases; choosing an input does not increase difficulty |
| medium | 5 | 3–5 business operations with filtering, detail, or one state change |
| hard | 5 | at least 6 operations with branching, approval, exception handling, cross-entity state, or audit trail |

Each case in `cases.json` contains the prompt contract that must reach Codex
CLI: `intent`, `goal`, `flow_steps`, `must_haves`, `acceptance_criteria`, and
`evaluation_method`. The runner maps these fields to the explicit
`DemoRequest.evaluation_*` fields; they are not hidden in a free-form scenario.

Every case also has a frozen browser contract. Its controls and journeys are
sent to Codex CLI, while the Runner keeps assertion text server-side. The
current core-generation score checks visible state changes, selector coverage,
artifact safety, and Reviewer evidence; it does not score OCR field
correctness. The held-out invoice gold file is reserved for a separate
data-extraction benchmark.

## Invoice fixtures

The ten files under `assets/invoices/` are downloaded from the public
[`alamgirqazi/invoice-ocr-synthetic` dataset](https://huggingface.co/datasets/alamgirqazi/invoice-ocr-synthetic). The dataset card describes them as
machine-generated fictional invoices and releases the data under CC BY 4.0.
The local files are pinned by SHA-256 in `invoice-manifest.json`; attribution
and the source URL are retained there. `invoice-gold.json` is a held-out
reference for later OCR/data-extraction work and must never be sent in a Codex
CLI Builder prompt.

The current Agent Core score evaluates generated Demo coverage, observable
browser interactions, artifact validation, safety boundaries, and Reviewer
evidence. It does not claim that the generated Demo correctly performs OCR.
For cases with assets, the Runner checksum-verifies and copies the JPG files
into the run-scoped Demo package; the Builder must reference each copied file
through a relative `assets/<filename>` path or its preserved subdirectory (the
invoice fixtures use `assets/invoices/<filename>`). This makes the input
material part of the browser-tested artifact without giving the model the
held-out gold.

In `core_generation` mode the authored case is the source of truth: the
orchestrator seeds the frozen browser contract, then calls the real Codex CLI
Builder, deterministic gates, Runner/Chromium, and independent Reviewer. It
does not spend model calls on the ordinary Brief/Manager/Discovery design
chain, and it never silently falls back to Mock.

## Run the set

Validate the complete set without starting a model process:

```powershell
uv run --project backend python scripts/run_codex_cli_eval_set.py --dry-run
```

Run one real Codex CLI case:

```powershell
uv run --project backend python scripts/run_codex_cli_eval_set.py --case-id simple-invoice-ocr-01 --real
```

Run a tier or the full 20-case set sequentially:

```powershell
uv run --project backend python scripts/run_codex_cli_eval_set.py --tier simple --real
uv run --project backend python scripts/run_codex_cli_eval_set.py --real
```

The script writes only a new JSON result under `results/` and stores normal
DemoPilot run evidence under `.data/runs/`. It checks that the backend reports
`codex_cli=true`, refuses to start without `--real`, and never sends the held-
out `invoice-gold.json` to Codex CLI.

The checked-in result files are evidence records, including failed real runs.
Do not turn a failed or incomplete run into a pass by editing its JSON; run the
case again and keep the new run id and denominator.
