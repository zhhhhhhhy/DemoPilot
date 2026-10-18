"""Paired real sales-intent experiment with runner-only acceptance answers.

Run with the project's Python environment. --dry-run never starts a model;
--real executes every selected case in both arms and retains failed arms in the
denominator. The intent arm asks questions before frozen seller answers are
released. Three authored cases are a pilot, not population-level causal proof.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from demopilot.config import Settings
from demopilot.core_harness import CodexCliHarness
from demopilot.core_loop import CoreBuilderLoop
from demopilot.models import DemoRequest, DemoRun, RunStatus, build_intent_statement
from demopilot.providers.codex_cli import CodexCliAgentProvider
from demopilot.storage import RunStore
from run_codex_cli_eval_set import compact_result, load_cases, resolve_assets
from run_sales_intent_agent_pilot import extract, intent_gate_errors

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("raw-sales", "intent-agent")
TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
# In the true one-sentence experiment the Core model gets the sales sentence
# through the request itself.  Do not duplicate inputs.json's scenario or
# audience fields in the mounted fixture, because that would leak a complete
# authored intent into the raw arm.  The two arms still share the same data
# fixtures and asset manifest.
INPUT_KEYS = ("schema_version", "case_id", "industry", "fixtures", "assets")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def redacted_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Expose interaction mechanics, never expected results or authored intent."""
    return {
        "schema_version": contract.get("schema_version", "core-acceptance-v2"),
        "case_id": contract["case_id"],
        "controls": dict(contract.get("controls", {})),
        "tests": [
            {"id": test.get("id", "interaction"), "steps": [
                {key: step[key] for key in ("action", "selector", "value") if key in step}
                for step in test.get("steps", [])
            ]}
            for test in contract.get("tests", [])
        ],
    }


@contextmanager
def masked_model_files(workspace: Path, case_id: str) -> Iterator[None]:
    """Restore original bytes even on cancellation; fail closed on tampering.

    Originals remain only in this trusted runner's memory during the model
    call. No backup containing answers is written inside the model workspace.
    """
    case_dir = workspace / "testdata" / case_id
    paths = (case_dir / "acceptance.json", case_dir / "inputs.json")
    originals = {path: path.read_bytes() for path in paths}
    contract = json.loads(originals[paths[0]])
    inputs = json.loads(originals[paths[1]])
    safe_inputs = {key: inputs[key] for key in INPUT_KEYS if key in inputs}
    safe_inputs["paths"] = {
        "inputs": f"testdata/{case_id}/inputs.json",
        "asset_root": f"testdata/{case_id}/assets",
    }
    replacements = {
        paths[0]: (json.dumps(redacted_contract(contract), ensure_ascii=False, indent=2) + "\n").encode(),
        paths[1]: (json.dumps(safe_inputs, ensure_ascii=False, indent=2) + "\n").encode(),
    }
    tampered: list[str] = []
    try:
        for path, content in replacements.items():
            path.write_bytes(content)
        yield
    finally:
        for path, expected in replacements.items():
            if not path.is_file() or path.read_bytes() != expected:
                tampered.append(path.name)
        for path, original in originals.items():
            path.write_bytes(original)
        if tampered:
            raise RuntimeError("Model modified protected redacted testdata: " + ", ".join(tampered))


def private_gate_prompt(prompt: str) -> str:
    prompt = prompt.replace(
        "- The contract contains the exact selectors, actions, values, and expected visible results. Treat it as the acceptance source of truth; do not invent a weaker test.",
        "- This experiment's model-visible contract contains only controls and interaction actions. Expected results are hidden from the model; the trusted runner checks them independently.",
    )
    return prompt + """

EXPERIMENT INPUT BOUNDARY
The model-visible acceptance.json is a controls/actions probe, not a complete
business correctness test. Its successful child probe cannot establish final
publication. Implement the sales description and supplied input fixtures. The
trusted runner alone checks hidden expectations after this model turn and may
return repair feedback. Never read source testdata, evaluation_sets, gold files,
run records, candidate outputs, or evidence folders outside this workspace.
Do not search the repository for the original acceptance answers. Read only the
supplied card, card-web, and this case's testdata; execute the named trusted
acceptance probe when asked. Do not modify acceptance.json, inputs.json, or the
harness-owned .codex configuration. Record all unresolved requirements honestly.
"""


class HiddenAnswerHarness(CodexCliHarness):
    """Same CLI harness, masked only while model/child can inspect testdata."""

    def __init__(self, provider: CodexCliAgentProvider, case_id: str):
        super().__init__(provider)
        self.case_id = case_id
        self.protected_input_violation = False

    async def build(self, **kwargs: Any) -> dict[str, Any]:
        if self.protected_input_violation:
            raise RuntimeError("Protected input violation already recorded; this run cannot publish")
        try:
            with masked_model_files(kwargs["workspace"], self.case_id):
                kwargs["prompt"] = private_gate_prompt(kwargs["prompt"])
                return await super().build(**kwargs)
        except RuntimeError as exc:
            if "modified protected redacted" in str(exc):
                self.protected_input_violation = True
            raise

    async def acceptance_check(self, **kwargs: Any) -> dict[str, Any]:
        if self.protected_input_violation:
            raise RuntimeError("Protected input violation already recorded; this run cannot publish")
        try:
            with masked_model_files(kwargs["workspace"], self.case_id):
                kwargs["prompt"] = private_gate_prompt(kwargs["prompt"])
                return await super().acceptance_check(**kwargs)
        except RuntimeError as exc:
            if "modified protected redacted" in str(exc):
                self.protected_input_violation = True
            raise


class TracingProvider(CodexCliAgentProvider):
    """Persist intent output incrementally, including failed/timeout turns."""

    intent_trace_dir: Path | None = None
    intent_trace_turn = 0

    async def _communicate_with_events(self, process: Any, prompt: bytes, on_event: Any) -> tuple[bytes, bytes]:
        self.intent_trace_turn += 1
        turn = self.intent_trace_turn
        try:
            if self.intent_trace_dir is None:
                return await super()._communicate_with_events(process, prompt, on_event)
            self.intent_trace_dir.mkdir(parents=True, exist_ok=True)
            stdout, stderr = await self._communicate_workspace_process(
                process, prompt, on_event,
                self.intent_trace_dir / f"turn-{turn:02d}-stdout.jsonl",
                self.intent_trace_dir / f"turn-{turn:02d}-stderr.log",
                mode="intent-read-only",
            )
        except BaseException as exc:
            if self.intent_trace_dir is not None:
                write_json(self.intent_trace_dir / f"turn-{turn:02d}-trace-error.json", {
                    "type": type(exc).__name__, "message": str(exc),
                    "boundary": "Partial stdout/stderr retained incrementally beside this record.",
                })
            raise
        if self.intent_trace_dir is not None:
            self.intent_trace_dir.mkdir(parents=True, exist_ok=True)
            (self.intent_trace_dir / f"turn-{turn:02d}-stdout.jsonl").write_bytes(stdout)
            (self.intent_trace_dir / f"turn-{turn:02d}-stderr.log").write_bytes(stderr)
        return stdout, stderr


def load_experiment_cases() -> list[dict[str, Any]]:
    """Load the *unexpanded* sales sentence and the frozen seller answers.

    The raw arm must receive exactly ``cases.json.raw_sales_brief``.  The
    treatment arm gets the same sentence on its first intent turn and only
    receives the seller answer script after the model asks for clarification.
    Gold intent and browser assertions remain outside this construction path.
    """
    descriptions = json.loads((ROOT / "evaluation_sets/sales-intent-v1/cases.json").read_text(encoding="utf-8"))
    _, sources = load_cases()
    result: list[dict[str, Any]] = []
    for item in descriptions["cases"]:
        source = sources[item["source_case_id"]]
        # Keep seller answer scripts outside testdata: the Core workspace may
        # mount testdata for fixture access, while these answers are trusted
        # experiment inputs that must be released only by the runner.
        clarification_path = ROOT / "evaluation_sets" / "sales-intent-v1" / "sales-clarifications" / f"{source['id']}.json"
        if not clarification_path.is_file():
            raise RuntimeError(f"Missing frozen seller clarification script: {clarification_path}")
        clarification_payload = json.loads(clarification_path.read_text(encoding="utf-8"))
        answers = clarification_payload.get("answers")
        if not isinstance(answers, list) or not answers:
            raise RuntimeError(f"Seller clarification script has no answers: {clarification_path}")
        inputs_path = ROOT / "testdata" / source["id"] / "inputs.json"
        inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
        fixture_data = {key: inputs[key] for key in INPUT_KEYS if key in inputs}
        result.append({
            **item, "raw_sales_brief": item["raw_sales_brief"], "source": source,
            "interview_input_policy": "sales-text-only",
            "clarification_answers": answers,
            "clarification_script": clarification_payload,
            "clarification_script_sha256": digest(clarification_path.read_bytes()),
            "input_data": fixture_data,
            "inputs_sha256": digest(inputs_path.read_bytes()),
            "contract_sha256": digest((inputs_path.parent / "acceptance.json").read_bytes()),
        })
    return result


def core_request(item: dict[str, Any], arm: str, intent: dict[str, Any] | None = None) -> DemoRequest:
    source = item["source"]
    assets, asset_hashes = resolve_assets(source)
    payload: dict[str, Any] = {
        "client_name": "Paired sales intent experiment",
        "project_name": source["name"], "industry": source["industry"],
        "scenario": item["raw_sales_brief"], "audience": "销售人员",
        "must_haves": [], "boundaries": ["只交付本地静态演示"],
        "priority": "完成销售描述中的功能并通过独立验收",
        "acceptance_criteria": [], "constraints": ["本地静态演示，不连接真实外部系统"],
        # The control is intentionally an unconfirmed one-sentence request;
        # only the interview treatment may mark typed intent as confirmed.
        "intent_confirmed": arm == "intent-agent", "provider": "codex_cli",
        "brand_tone": source.get("brand_tone", "清晰、克制、可验证"),
        "primary_color": source.get("primary_color", "#0071e3"),
        "evaluation_mode": "core_generation", "evaluation_prompt_profile": "treatment-current",
        "evaluation_intent_profile": arm, "evaluation_case_id": source["id"],
        "evaluation_dataset": "codex-cli-v1", "evaluation_difficulty": source["difficulty"],
        "evaluation_assets": assets, "evaluation_asset_sha256": asset_hashes,
        # Never serialize the hidden browser contract in the model request.
        "evaluation_browser_contract": {},
    }
    if intent is not None:
        payload.update(
            audience=intent["actor"], must_haves=intent["must_haves"],
            acceptance_criteria=intent["acceptance_criteria"], constraints=intent["constraints"],
            evaluation_intent=intent["problem"], evaluation_goal=intent["desired_outcome"],
            evaluation_flow_steps=intent["flow_steps"], evaluation_method=intent["acceptance_criteria"],
        )
    return DemoRequest.model_validate(payload)


def final_pass(result: dict[str, Any]) -> bool:
    return (
        result.get("status") == "completed"
        and result.get("publication_status") == "published"
        and result.get("quality_gate") == "passed"
        and result.get("browser_status") == "passed"
        and result.get("post_publish_audit_status") == "passed"
        and result.get("post_publish_browser_status") == "passed"
        and result.get("post_publish_fresh_browser_context") is True
        and not result.get("browser_issues")
        and not result.get("post_publish_browser_issues")
        and not result.get("intent_gate_errors")
        and not result.get("error")
    )


def summarize(results: list[dict[str, Any]], case_ids: list[str]) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm in ARMS:
        rows = [row for row in results if row["arm"] == arm]
        passes = sum(bool(row.get("final_pass")) for row in rows)
        arms[arm] = {
            "case_count": len(case_ids), "terminal_count": len(rows),
            "final_pass_count": passes, "final_pass_rate": f"{passes}/{len(case_ids)}",
            "revision_total": sum(row.get("revision_count", 0) for row in rows),
            "first_pass_count": sum(bool(row.get("final_pass")) and row.get("revision_count") == 0 for row in rows),
            "cli_calls_total": sum(row.get("total_cli_calls", 0) for row in rows),
            "intent_cli_calls": sum(row.get("intent_cli_calls", 0) for row in rows),
            "intent_turns_total": sum(row.get("intent_turns", 0) for row in rows),
            "seller_answer_release_count": sum(bool(row.get("seller_answers_released")) for row in rows),
        }
    complete = all(arms[arm]["terminal_count"] == len(case_ids) for arm in ARMS)
    paired = []
    for case_id in case_ids:
        rows = {row["arm"]: row for row in results if row["case_id"] == case_id}
        if all(arm in rows for arm in ARMS):
            control, treatment = rows[ARMS[0]], rows[ARMS[1]]
            paired.append({"case_id": case_id, "control_final_pass": control["final_pass"],
                "treatment_final_pass": treatment["final_pass"],
                "revision_difference_treatment_minus_control": treatment["revision_count"] - control["revision_count"],
                "cli_call_difference_treatment_minus_control": treatment["total_cli_calls"] - control["total_cli_calls"]})
    treatment, control = arms[ARMS[1]], arms[ARMS[0]]
    observed_improvement = complete and (
        treatment["final_pass_count"] > control["final_pass_count"]
        or (treatment["final_pass_count"] == control["final_pass_count"]
            and treatment["revision_total"] < control["revision_total"]))
    return {"arms": arms, "all_selected_terminal": complete, "paired": paired,
            "observed_improvement": observed_improvement,
            "causal_claim": "not_estimated; three authored cases, one paired execution each"}


async def run_arm(item: dict[str, Any], arm: str, store: RunStore,
                  provider: CodexCliAgentProvider, output_dir: Path,
                  max_revision_rounds: int = 4) -> dict[str, Any]:
    trace_dir = output_dir / item["id"] / arm
    trace_dir.mkdir(parents=True, exist_ok=True)
    result_path, progress_path = trace_dir / "result.json", trace_dir / "progress.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    intent_calls = 0
    intent_turns = 0
    seller_answers_released = False
    gate_errors: list[str] = []
    started_at = datetime.now(UTC).isoformat()
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        run = store.get(progress["run_id"])
        if run is None:
            raise RuntimeError("Progress refers to missing durable run")
        intent_calls = progress.get("intent_cli_calls", 0)
        intent_turns = progress.get("intent_turns", 0)
        seller_answers_released = progress.get("seller_answers_released", False)
        gate_errors = progress.get("intent_gate_errors", [])
        started_at = progress["started_at"]
        if run.status not in TERMINAL:
            raise RuntimeError(f"Run {run.id} is not terminal. Inspect its process before resuming; no duplicate CLI launched.")
        # A cancelled or failed process may have persisted the DemoRun before
        # the outer runner was interrupted. Finalize that terminal record
        # without launching Core again; resuming must never duplicate a CLI
        # arm that already has a durable terminal state.
        result = compact_result(item["source"], run.model_dump(mode="json"))
        result.update(arm=arm, intent_cli_calls=intent_calls,
                      intent_turns=intent_turns,
                      seller_answers_released=seller_answers_released,
                      intent_gate_errors=gate_errors,
                      total_cli_calls=run.agent_calls + intent_calls,
                      started_at=started_at,
                      finished_at=datetime.now(UTC).isoformat(),
                      run_dir=str(store.run_dir(run.id)))
        result["final_pass"] = final_pass(result)
        write_json(result_path, result)
        progress.update(status="terminal", terminal_status=str(run.status),
                        intent_cli_calls=intent_calls,
                        intent_turns=intent_turns,
                        seller_answers_released=seller_answers_released,
                        intent_gate_errors=gate_errors,
                        final_pass=result["final_pass"])
        write_json(progress_path, progress)
        return result
    else:
        run = DemoRun(id=uuid4().hex[:12], request=core_request(item, arm))
        store.create(run)
        progress = {"case_id": item["id"], "arm": arm, "run_id": run.id,
                    "started_at": started_at, "status": "allocated", "intent_cli_calls": 0}
        write_json(progress_path, progress)  # Allocation is durable before any model call.
        try:
            if arm == "intent-agent":
                progress["status"] = "intent_running"
                write_json(progress_path, progress)
                if isinstance(provider, TracingProvider):
                    provider.intent_trace_dir = trace_dir / "intent"
                    provider.intent_trace_turn = 0
                extracted, events = await extract(provider, item, trace_dir / "intent")
                intent_calls = sum(event.get("type") == "process.started" for event in events)
                intent_turns = intent_calls
                seller_answers_released = (trace_dir / "intent" / "seller-answers-released.json").is_file()
                gate_errors = intent_gate_errors(extracted, item["id"])
                progress.update(intent_cli_calls=intent_calls, intent_turns=intent_turns,
                                seller_answers_released=seller_answers_released,
                                intent_gate_errors=gate_errors)
                write_json(progress_path, progress)
                if gate_errors:
                    run.status = RunStatus.FAILED
                    run.publication_status = "cannot_complete"
                    run.quality_gate = "failed"
                    run.error = "Intent delivery gate failed: " + "; ".join(gate_errors)
                    run.checkpoint = "intent:delivery_failed"
                    store.save(run)
                else:
                    run.request = core_request(item, arm, extracted)
            if not gate_errors:
                run.outputs["intent_statement"] = build_intent_statement(run.request)
                store.save(run)
                progress["status"] = "core_running"
                write_json(progress_path, progress)
                loop = CoreBuilderLoop(store, HiddenAnswerHarness(provider, item["id"]),
                                       project_root=ROOT, max_revision_rounds=max_revision_rounds)
                await loop.execute(run)
        except BaseException as exc:
            # All model file masks have already restored originals in finally.
            if arm == "intent-agent" and isinstance(provider, TracingProvider):
                intent_calls = max(intent_calls, provider.intent_trace_turn)
            if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                run.status = RunStatus.CANCELLED
                run.publication_status = "hidden"
            else:
                run.status = RunStatus.FAILED
                run.publication_status = "cannot_complete"
            run.quality_gate = "failed"
            run.current_agent = None
            run.error = f"{type(exc).__name__}: {exc}"[:500]
            store.save(run)
            write_json(trace_dir / "execution-error.json", {"type": type(exc).__name__, "message": str(exc)})
            if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                raise
    result = compact_result(item["source"], run.model_dump(mode="json"))
    result.update(arm=arm, intent_cli_calls=intent_calls, intent_turns=intent_turns,
                  seller_answers_released=seller_answers_released,
                  intent_gate_errors=gate_errors,
                  clarification_script_sha256=item.get("clarification_script_sha256"),
                  interview_input_policy=item.get("interview_input_policy"),
                  total_cli_calls=run.agent_calls + intent_calls, started_at=started_at,
                  finished_at=datetime.now(UTC).isoformat(), run_dir=str(store.run_dir(run.id)))
    result["final_pass"] = final_pass(result)
    write_json(result_path, result)
    progress.update(status="terminal", terminal_status=str(run.status), intent_cli_calls=intent_calls,
                    intent_turns=intent_turns, seller_answers_released=seller_answers_released,
                    intent_gate_errors=gate_errors, final_pass=result["final_pass"])
    write_json(progress_path, progress)
    return result


async def async_main(args: argparse.Namespace) -> int:
    cases = load_experiment_cases()
    if args.case_id:
        requested = set(args.case_id)
        unknown = requested - {item["id"] for item in cases}
        if unknown:
            raise ValueError(f"Unknown case ids: {sorted(unknown)}")
        cases = [item for item in cases if item["id"] in requested]
    settings = Settings()
    runtime = {"command": settings.codex_command, "model": args.model,
               "reasoning_effort": settings.codex_reasoning_effort,
               "cli_timeout_seconds": args.cli_timeout, "max_revision_rounds": args.max_revision_rounds,
               "data_dir": str(settings.data_dir.resolve())}
    context = {"schema_version": "sales-intent-paired-real-v2", "runtime": runtime,
               "code_sha256": {str(path): digest((ROOT / path).read_bytes()) for path in (
                   Path("scripts/run_sales_intent_paired_real.py"), Path("scripts/run_sales_intent_agent_pilot.py"),
                   Path("backend/src/demopilot/providers/codex_cli.py"), Path("backend/src/demopilot/core_loop.py"),
                   Path("backend/src/demopilot/core_acceptance.py"), Path("backend/src/demopilot/prompts.py"))},
               "case_ids": [item["id"] for item in cases],
               "input_policy": "A Core receives exactly cases.json.raw_sales_brief. B intent turn 1 receives only that same sales text (ordinary fixture values are withheld); frozen seller answers are released only after the model returns needs_clarification. After intent, both Core runs receive the same ordinary fixtures; hidden assertions and gold remain evaluator-only.",
               "cases": [{key: item[key] for key in ("id", "difficulty", "raw_sales_brief", "input_data", "inputs_sha256", "contract_sha256", "clarification_script_sha256")} for item in cases],
               "arm_order": {item["id"]: list(ARMS if index % 2 == 0 else reversed(ARMS)) for index, item in enumerate(cases)}}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    context_path = args.output_dir / "experiment-context.json"
    if context_path.exists():
        if json.loads(context_path.read_text(encoding="utf-8")) != context:
            raise RuntimeError("Frozen experiment context differs. Use a new output directory; do not mix results.")
    else:
        write_json(context_path, context)
    if args.dry_run:
        for item in cases:
            core_request(item, ARMS[0])
            contract = json.loads((ROOT / "testdata" / item["id"] / "acceptance.json").read_text(encoding="utf-8"))
            write_json(args.output_dir / item["id"] / "model-visible-contract.json", redacted_contract(contract))
        write_json(args.output_dir / "dry-run.json", {"real_runs": False, "case_count": len(cases), "arm_count": 2,
                   "context": str(context_path), "hidden_answers_excluded": True})
        print(json.dumps({"dry_run": True, "cases": len(cases), "output_dir": str(args.output_dir)}), flush=True)
        return 0
    provider = TracingProvider(command=settings.codex_command, model=args.model,
        reasoning_effort=settings.codex_reasoning_effort, timeout_seconds=args.cli_timeout, cwd=ROOT)
    if not provider.available():
        raise RuntimeError("Codex CLI executable unavailable")
    store = RunStore(settings.data_dir)
    results: list[dict[str, Any]] = []
    for item in cases:
        for arm in context["arm_order"][item["id"]]:
            result = await run_arm(item, arm, store, provider, args.output_dir, args.max_revision_rounds)
            results.append(result)
            report = {"schema_version": "sales-intent-paired-real-v2", "real_runs": True,
                "runtime": runtime, "cases": context["case_ids"], "results": results,
                **summarize(results, context["case_ids"]),
                "evidence_boundary": "Core full prompt/stdout JSONL/stderr retained in run artifacts. Completed intent turns retain exact prompt/context/output/raw stdout JSONL/stderr/events. Interrupted intent communication records the missing partial-stdout boundary."}
            write_json(args.output_dir / "paired-results.json", report)
            print(json.dumps({"case_id": item["id"], "arm": arm, "run_id": result["run_id"],
                "final_pass": result["final_pass"], "revisions": result["revision_count"], "calls": result["total_cli_calls"]}, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--cli-timeout", type=float, default=600)
    parser.add_argument("--max-revision-rounds", type=int, default=4)
    parser.add_argument("--model", default="gpt-6.1-sol")
    args = parser.parse_args()
    if args.real == args.dry_run:
        parser.error("Choose exactly one of --real or --dry-run")
    if not 1 <= args.cli_timeout <= 600:
        parser.error("--cli-timeout must be between 1 and 600 seconds")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
