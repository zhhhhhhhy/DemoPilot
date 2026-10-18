"""Frozen, source-derived quotation clarification experiment using real CLI.

Development and held-out outputs live in separate immutable contexts. The
engineering publication gate is shared. Full business gold is offline-only
and NEVER enters Core repair feedback. This estimates the effect of acquiring
configured seller information, not a magic wording or model-capability effect.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from demopilot.config import Settings
from demopilot.core_harness import CodexCliHarness
from demopilot.core_loop import CoreBuilderLoop
from demopilot.models import DemoRequest, DemoRun, RunStatus, build_intent_statement
from demopilot.prompts import SYSTEM_PROMPT, build_agent_prompt
from demopilot.run_metrics import run_metrics
from demopilot.storage import RunStore
from run_sales_intent_agent_pilot import intent_gate_errors
from run_sales_intent_paired_real import TracingProvider, write_json
from run_codex_cli_eval_set import compact_result
from materialize_quotation_intent import COMMON_FACTS

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation_sets" / "quotation-intent-v1"
ARMS = ("direct", "clarify")
TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
FROZEN_CODE = [
    "scripts/run_quotation_intent_ab.py", "scripts/audit_quotation_intent.py",
    "scripts/quotation_oracle.py", "scripts/materialize_quotation_intent.py",
    "scripts/run_sales_intent_paired_real.py", "scripts/run_sales_intent_agent_pilot.py",
    "scripts/run_codex_cli_eval_set.py",
    "backend/src/demopilot/core_loop.py", "backend/src/demopilot/core_harness.py",
    "backend/src/demopilot/core_acceptance.py", "backend/src/demopilot/models.py",
    "backend/src/demopilot/prompts.py", "backend/src/demopilot/providers/codex_cli.py",
    "backend/src/demopilot/config.py", "backend/src/demopilot/run_metrics.py",
    "backend/src/demopilot/storage.py", "backend/src/demopilot/harness.py",
    "scripts/core_acceptance_cli.py",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def all_cases():
    return load_json(DATASET / "cases.json")["cases"]


def freeze_context(args):
    cases = [case for case in all_cases() if case["split"] == args.split]
    manifest = load_json(DATASET / "manifest.json")
    for relative, expected in manifest["files"].items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError(f"Dataset changed: {relative}")
    source_urls = {source["url"] for source in load_json(DATASET / "sources.json")["sources"]}
    if any(set(case["source_urls"]) - source_urls for case in all_cases()):
        raise RuntimeError("A requirement lacks verified source provenance")
    context = dict(
        schema_version="quotation-intent-ab-v1", protocol_revision=2, split=args.split,
        case_ids=[case["id"] for case in cases],
        model=args.model, reasoning_effort="medium", cli_timeout_seconds=args.cli_timeout,
        max_revision_rounds=2, max_intent_turns=3, intent_timeout_seconds=120,
        max_parallel_cases=2,
        arm_order={case["id"]: list(ARMS if index % 2 == 0 else reversed(ARMS))
                   for index, case in enumerate(cases)},
        code_sha256={path: sha(ROOT / path) for path in FROZEN_CODE},
        data_manifest_sha256=sha(DATASET / "manifest.json"),
        source_registry_sha256=sha(DATASET / "sources.json"),
        comparison="Same initial phrase, ordinary fixtures, UI contract, Core model and repair budget. Clarify receives seller facts only after appropriate questions, plus typed intent. Direct receives no seller facts. Final business scoring is independent and never fed back.",
        primary_endpoint="All required independent business journeys pass AND the original Core run published.",
        negative_findings_policy="Unpublished, intent failures, infrastructure failures, unverified UI and published wrong outputs remain in full denominator.",
        limitation="Ten documentation-derived configurations from one product family; scripted seller, one paired execution per independent task; no customer adoption or broad causal-effect claim.",
        storage_policy="Isolated experiment RunStore under this results directory; engineering-published artifacts are not added to the product dashboard.",
    )
    return context, cases


def source_meta(case):
    return dict(id=case["id"], name=f"报价演示 {case['id'][-2:]}", industry="B2B",
                difficulty="medium", flow_steps=["选择商品和客户", "输入数量和日期", "计算并查看报价"])


def make_request(case, arm, intent=None, answers=None):
    payload = dict(
        client_name="Quotation evaluation", project_name=f"报价演示 {case['id'][-2:]}",
        industry="B2B", scenario=case["raw_sales_brief"], audience="销售人员",
        provider="codex_cli", evaluation_mode="core_generation",
        evaluation_dataset="quotation-intent-v1", evaluation_case_id=case["id"],
        evaluation_difficulty="medium", evaluation_prompt_profile="treatment-current",
        evaluation_intent_profile="intent-agent" if arm == "clarify" else "raw-sales",
        evaluation_intent=case["raw_sales_brief"],
        priority="完成销售所描述的本地报价演示",
        boundaries=["仅本地静态演示，不连接真实交易系统"], intent_confirmed=arm == "clarify",
        must_haves=[], acceptance_criteria=[], constraints=["使用同一组给定商品和客户样例"],
    )
    if intent is not None:
        # Preserve source answers verbatim so list-field truncation cannot silently
        # drop the seller's actual rule. This is explicitly part of the treatment.
        facts = "\n".join(answers or [])
        payload.update(
            audience=intent["actor"], must_haves=intent["must_haves"],
            acceptance_criteria=intent["acceptance_criteria"],
            evaluation_intent=case["raw_sales_brief"] + "\n销售已回答：" + facts,
            evaluation_goal=intent["desired_outcome"],
            evaluation_flow_steps=intent["flow_steps"],
            evaluation_method=intent["acceptance_criteria"],
        )
    return DemoRequest.model_validate(payload)


def matched_seller_answers(questions, script, previously_released):
    question_text = " ".join(str(q).lower() for q in questions)
    newly_released = []
    matches = []
    complete_request = [alias for alias in script.get("complete_rule_question_aliases", [])
                        if alias.lower() in question_text]
    for answer in script["answers"]:
        if answer["topic"] in previously_released:
            continue
        aliases = [alias for alias in answer["question_aliases"] if alias.lower() in question_text]
        if aliases or complete_request:
            newly_released.append(answer)
            matches.append(dict(topic=answer["topic"], matched_aliases=aliases,
                                complete_rule_request=complete_request, questions=questions))
    return newly_released, matches


class QuotationIntentProvider(TracingProvider):
    async def _communicate_with_events(self, process, prompt, on_event):
        if self.intent_trace_dir is not None:
            self.intent_trace_dir.mkdir(parents=True, exist_ok=True)
            (self.intent_trace_dir / f"turn-{self.intent_trace_turn + 1:02d}-stdin.txt").write_bytes(prompt)
        return await super()._communicate_with_events(process, prompt, on_event)


async def interview(provider, case, trace_dir):
    trace_dir.mkdir(parents=True, exist_ok=True)
    provider.intent_trace_dir, provider.intent_trace_turn = trace_dir, 0
    script = load_json(DATASET / case["seller_script"])
    request = make_request(case, "direct")
    context = dict(
        intent_context=dict(case_id=case["id"], raw_sales_brief=case["raw_sales_brief"],
                            difficulty="medium", input_policy="sales text only; catalogue is supplied to Builder later"),
        sales_brief=case["raw_sales_brief"], clarification_answers=[],
        shared_engineering_conventions=COMMON_FACTS,
        interview_policy="Ask about business rules that change quote outcomes, covering applicability, numerical parameters and rule composition when missing. Layout and wording may be chosen freely. The catalogue is provided later, so do not block waiting for a file. Only stated seller facts are authoritative; do not invent rates or thresholds.",
    )
    events = []
    released_topics = set()
    released_facts = []

    def event_callback(event):
        events.append(event)
        write_json(trace_dir / "events.json", events)

    result = {}
    for turn in range(1, 4):
        write_json(trace_dir / f"turn-{turn:02d}-context.json", context)
        prompt = SYSTEM_PROMPT + "\n\n" + build_agent_prompt("intent", request, context)
        (trace_dir / f"turn-{turn:02d}-prompt.txt").write_text(prompt, encoding="utf-8")
        result = await provider.run_agent("intent", request, context, on_event=event_callback)
        stdout_path = trace_dir / f"turn-{turn:02d}-stdout.jsonl"
        if stdout_path.exists():
            prohibited = []
            for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item = entry.get("item", {})
                if item.get("type") in {"command_execution", "mcp_tool_call", "web_search"}:
                    prohibited.append(item)
            if prohibited:
                write_json(trace_dir / "input-boundary-violation.json", dict(tool_calls=prohibited))
                result["_runner_interview_errors"] = ["Intent used a tool despite text-only input policy"]
                break
        write_json(trace_dir / f"turn-{turn:02d}-output.json", result)
        if result.get("status") == "ready":
            break
        if result.get("status") != "needs_clarification":
            break
        questions = result.get("questions", [])
        newly_released, matches = matched_seller_answers(questions, script, released_topics)
        for answer in newly_released:
            released_topics.add(answer["topic"])
            released_facts.append(answer["text"])
        response = [answer["text"] for answer in newly_released] or [script["fallback"]]
        write_json(trace_dir / f"turn-{turn:02d}-seller-response.json",
                   dict(released_after_turn=turn, questions=questions, matches=matches,
                        answers=response, new_business_topics=[a["topic"] for a in newly_released]))
        context["previous_intent"] = result
        context["clarification_answers"] = [*released_facts, script["fallback"]]
    write_json(trace_dir / "intent-output.json", result)
    write_json(trace_dir / "released-topics.json", dict(topics=sorted(released_topics), facts=released_facts))
    return result, released_facts, provider.intent_trace_turn


class QuotationLoop(CoreBuilderLoop):
    def _goal_prompt(self, run, workspace, case_id, iteration, feedback):
        prompt = super()._goal_prompt(run, workspace, case_id, iteration, feedback)
        return prompt + """

QUOTATION EXPERIMENT BOUNDARY
The supplied acceptance.json is the shared engineering/UI gate. It checks
operability and input validation, not the seller's private pricing preferences.
Implement the sales facts actually supplied; document assumptions rather than
inventing confirmed seller requirements. Final business scoring is offline and
never supplied as repair advice. Read only this workspace's card, card-web and
testdata. Do not read the repository's evaluation_sets, seller-answers, private
oracle, other runs, or results. The UI outputs must show one numeric amount per
documented result element, including zeros; the free-quantity is an additional
gift count, not a paid quantity. The displayed #subtotal minus the displayed
price adjustment plus tax must equal payable amount. #subtotal is the original
net amount when catalogue prices include tax; never add included tax twice.
Keep all contract controls visible.
"""


async def run_arm(case, arm, output_dir, context):
    target = output_dir / case["id"] / arm
    target.mkdir(parents=True, exist_ok=True)
    result_path, progress_path = target / "result.json", target / "progress.json"
    if result_path.exists():
        return load_json(result_path)
    settings = Settings()
    store = RunStore(output_dir / "runtime")
    if progress_path.exists():
        progress = load_json(progress_path)
        run = store.get(progress["run_id"])
        if run is None or run.status not in TERMINAL:
            raise RuntimeError("Inspect interrupted nonterminal run first; duplicate Core launch prohibited")
        started = progress["started_at"]
        elapsed = max(0, (run.updated_at - datetime.fromisoformat(started)).total_seconds())
        intent_calls = progress.get("intent_calls", 0)
    else:
        started = datetime.now(UTC).isoformat()
        started_clock = time.monotonic()
        run = DemoRun(id=uuid4().hex[:12], request=make_request(case, arm))
        store.create(run)
        progress = dict(run_id=run.id, started_at=started, status="allocated", intent_calls=0)
        write_json(progress_path, progress)
        intent_calls = 0
        try:
            if arm == "clarify":
                progress["status"] = "intent_running"
                write_json(progress_path, progress)
                intent_provider = QuotationIntentProvider(command=settings.codex_command, model=context["model"],
                                                 reasoning_effort="medium", timeout_seconds=120, cwd=ROOT)
                intent, facts, intent_calls = await interview(intent_provider, case, target / "intent")
                progress["intent_calls"] = intent_calls
                write_json(progress_path, progress)
                errors = intent_gate_errors(intent, case["id"])
                if errors:
                    run.status = RunStatus.FAILED
                    run.publication_status = "cannot_complete"
                    run.quality_gate = "failed"
                    run.error = "Intent delivery failed: " + "; ".join(errors)
                    run.checkpoint = "intent:delivery_failed"
                    store.save(run)
                else:
                    run.request = make_request(case, arm, intent, facts)
            if run.status not in TERMINAL:
                run.outputs["intent_statement"] = build_intent_statement(run.request)
                store.save(run)
                progress["status"] = "core_running"
                write_json(progress_path, progress)
                core_provider = TracingProvider(command=settings.codex_command, model=context["model"],
                                               reasoning_effort="medium",
                                               timeout_seconds=context["cli_timeout_seconds"], cwd=ROOT)
                await QuotationLoop(store, CodexCliHarness(core_provider), project_root=ROOT,
                                    max_revision_rounds=context["max_revision_rounds"]).execute(run)
        except BaseException as exc:
            if arm == "clarify" and "intent_provider" in locals():
                intent_calls = max(intent_calls, intent_provider.intent_trace_turn)
            run.status = RunStatus.CANCELLED if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else RunStatus.FAILED
            run.publication_status = "hidden"
            run.quality_gate = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:800]
            store.save(run)
            write_json(target / "execution-error.json", dict(type=type(exc).__name__, message=str(exc)))
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                raise
        elapsed = time.monotonic() - started_clock
    row = compact_result(source_meta(case), run.model_dump(mode="json"))
    row.update(arm=arm, split=case["split"], elapsed_seconds=round(elapsed, 3),
               intent_cli_calls=intent_calls, total_cli_calls=run.agent_calls + intent_calls,
               started_at=started, finished_at=datetime.now(UTC).isoformat(),
               run_dir=str(store.run_dir(run.id)), business_status="not_run")
    write_json(result_path, row)
    write_json(target / "run-metrics.json", run_metrics(run, store.run_dir(run.id)))
    progress.update(status="terminal", intent_calls=intent_calls, terminal_status=run.status.value)
    write_json(progress_path, progress)
    return row


async def execute(args, context, cases):
    results = []
    case_gate, record_lock = asyncio.Semaphore(context["max_parallel_cases"]), asyncio.Lock()

    async def run_pair(case):
        async with case_gate:
            for arm in context["arm_order"][case["id"]]:
                # Any source, data, or runner change invalidates continuation.
                current, _ = freeze_context(args)
                if current != context:
                    raise RuntimeError("Frozen context changed; no further model call started")
                row = await run_arm(case, arm, args.output_dir, context)
                async with record_lock:
                    results.append(row)
                    write_json(args.output_dir / "results.json", dict(
                        real_cli=True, split=args.split, planned_case_count=len(cases),
                        planned_arm_count=2 * len(cases), results=results,
                        business_scoring="Run separate frozen audit after all arms; no scoring feedback to Builder."))
                print(json.dumps({key: row.get(key) for key in
                                  ("case_id", "arm", "run_id", "status", "publication_status",
                                   "revision_count", "total_cli_calls", "elapsed_seconds")}), flush=True)

    await asyncio.gather(*(run_pair(case) for case in cases))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "heldout"), required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--cli-timeout", type=float, default=300)
    parser.add_argument("--model", default="gpt-6.1-sol")
    args = parser.parse_args()
    if args.freeze == args.real:
        parser.error("Choose --freeze or --real")
    context, cases = freeze_context(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    context_path = args.output_dir / "context.json"
    if args.freeze:
        if context_path.exists():
            raise RuntimeError("Refusing to replace an existing frozen context")
        write_json(context_path, context)
        write_json(args.output_dir / "freeze-record.json",
                   dict(created_at=datetime.now(UTC).isoformat(), real_runs=False,
                        context_sha256=sha(context_path), split=args.split,
                        case_count=len(cases), all_case_ids=[c["id"] for c in all_cases()]))
        archive = args.output_dir / "frozen-code"
        for relative in FROZEN_CODE:
            path = archive / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())
        data_archive = args.output_dir / "frozen-data"
        for relative in load_json(DATASET / "manifest.json")["files"]:
            target = data_archive / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        for name in ("manifest.json", "sources.json"):
            target = data_archive / "evaluation_sets" / "quotation-intent-v1" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((DATASET / name).read_bytes())
        print(json.dumps(dict(frozen=True, cases=len(cases), split=args.split)))
    else:
        if not context_path.exists() or load_json(context_path) != context:
            raise RuntimeError("Freeze exact code/data/model conditions before --real")
        asyncio.run(execute(args, context, cases))


if __name__ == "__main__":
    main()
