"""Run a real Codex CLI intent-extraction step, then the same Core Builder.

This is the first experiment that exercises an AI intent step. It intentionally
keeps the authored browser contract as the engineering gate, so the report
separates intent fidelity from downstream publication rather than calling a
published result an intent-accuracy score.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

from demopilot.config import Settings
from demopilot.models import DemoRequest
from demopilot.prompts import SYSTEM_PROMPT, build_agent_prompt
from demopilot.providers.codex_cli import CodexCliAgentProvider
from run_codex_cli_eval_set import compact_result, resolve_assets, wait_for_run
from run_codex_cli_intent_ab import load_intent_cases


ROOT = Path(__file__).resolve().parents[1]


INTENT_ALIASES: dict[str, tuple[str, ...]] = {
    "套餐选择": ("套餐选择", "选择一个套餐", "套餐选择控件"),
    "席位数量": ("席位数量", "选择席位数", "席位数", "席位数选择控件"),
    "报价总额": ("报价总额", "即时的演示报价", "演示报价", "显示即时的演示报价", "总价"),
    "行业筛选": ("行业筛选", "按行业筛选", "行业筛选控件"),
    "线索详情": ("线索详情", "查看详情"),
    "负责人选择": ("负责人选择", "分配负责人"),
    "跟进行动状态": ("跟进行动状态", "创建一次跟进行动", "跟进状态"),
    "供应商比较表": ("供应商比较表", "比较三家供应商", "供应商比较"),
    "推荐方案选择": ("推荐方案选择", "选择方案", "方案选择"),
    "采购理由校验": ("采购理由校验", "填写理由", "理由校验"),
    "审批分支": ("审批分支", "批准或驳回", "批准和驳回"),
    "审计时间线": ("审计时间线", "审计记录", "时间线"),
}


def norm(value: Any) -> str:
    return "".join(str(value).lower().split())


def list_f1(predicted: list[str], gold: list[str]) -> dict[str, float]:
    pred = [norm(item) for item in predicted if norm(item)]
    expected = [norm(item) for item in gold if norm(item)]
    matched: set[int] = set()
    for item in pred:
        for index, target in enumerate(expected):
            aliases = {norm(alias) for alias in INTENT_ALIASES.get(target, (target,))}
            if index not in matched and any(alias in item for alias in aliases):
                matched.add(index)
                break
    tp = len(matched)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def intent_gate_errors(output: dict[str, Any], case_id: str) -> list[str]:
    """Validate the model's delivery contract without consulting evaluator gold."""
    errors: list[str] = []
    if output.get("schema_version") != "sales-intent-v2":
        errors.append("schema_version must be sales-intent-v2")
    if output.get("case_id") != case_id:
        errors.append("case_id must match the selected sales case")
    for field in ("actor", "problem", "desired_outcome"):
        if not isinstance(output.get(field), str) or not output[field].strip():
            errors.append(f"{field} must be a nonempty string")
    for field in (
        "must_haves", "flow_steps", "acceptance_criteria", "constraints",
        "non_goals", "assumptions", "questions",
    ):
        value = output.get(field)
        if not isinstance(value, list) or len(value) > 8 or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            errors.append(f"{field} must be an array of at most 8 nonempty strings")
        # The compiler is forbidden to invent an unstated business sequence.
        # A present empty flow_steps list is faithful when no order was given;
        # the Builder can plan UI operations from the confirmed capabilities.
        elif field in {"must_haves", "acceptance_criteria"} and not value:
            errors.append(f"{field} must not be empty")
    confidence = output.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence must be a number from 0 to 1")
    traceability = output.get("traceability")
    if not isinstance(traceability, list) or not traceability or any(
        not isinstance(item, dict)
        or not isinstance(item.get("field"), str)
        or not item["field"].strip()
        or not isinstance(item.get("source_quote"), str)
        or not item["source_quote"].strip()
        for item in traceability
    ):
        errors.append("traceability must contain field/source_quote evidence")
    if output.get("status") != "ready":
        errors.append("status is not ready")
    if output.get("questions") != []:
        errors.append("unresolved questions remain")
    for error in output.get("_runner_interview_errors", []):
        if isinstance(error, str) and error.strip():
            errors.append(error.strip())
    return errors


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _question_topic_audit(output: dict[str, Any], answers: list[Any]) -> dict[str, Any]:
    """Classify whether the model's questions cover frozen seller topics.

    This is a runner-side diagnostic/gate only.  Topic aliases never enter
    the model prompt, and the answer text is released only when every answer
    marked ``required_before_core`` has a matching model question.
    """
    questions = [norm(value) for value in output.get("questions", []) if isinstance(value, str)]
    required: list[dict[str, Any]] = []
    for item in answers:
        if not isinstance(item, dict):
            continue
        aliases = [norm(alias) for alias in item.get("allowed_question_aliases", []) if isinstance(alias, str)]
        if item.get("required_before_core", False):
            required.append({"topic": item.get("question_topic", ""), "aliases": aliases})
    matched: list[str] = []
    missing: list[str] = []
    for item in required:
        topic = str(item["topic"])
        if any(alias and any(alias in question for question in questions) for alias in item["aliases"]):
            matched.append(topic)
        else:
            missing.append(topic)
    return {"required_topics": [item["topic"] for item in required], "matched_topics": matched,
            "missing_topics": missing, "questions": output.get("questions", [])}


def _intent_prompt(request: DemoRequest, context: dict[str, Any]) -> str:
    """Record the exact prompt assembled by the read-only CLI provider."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "你现在通过本地 Codex CLI 作为 DemoPilot 的一个 Agent 工作。"
        "只能依据下面给出的客户输入和前序证据作答；不要调用工具、不要读写文件、"
        "不要输出思考过程。"
        "最终只返回一个符合 JSON Schema 的对象，格式必须是"
        '{"payload":"..."}；payload 的值是你本来要返回的 JSON 对象序列化后的单行字符串，'
        "不要使用 Markdown 或代码围栏。\n\n"
        + build_agent_prompt("intent", request, context)
    )


def score_intent(output: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    must = list_f1(output.get("must_haves", []), gold["must_haves"])
    predicted_flow = [norm(item) for item in output.get("flow_steps", [])]
    gold_flow = [norm(item) for item in gold["flow_steps"]]
    matched = sum(1 for item in gold_flow if any(item in candidate or candidate in item for candidate in predicted_flow))
    flow_recall = matched / len(gold_flow) if gold_flow else 1.0
    positions = [next((index for index, candidate in enumerate(predicted_flow) if item in candidate or candidate in item), -1) for item in gold_flow]
    positions = [item for item in positions if item >= 0]
    order = 1.0 if positions == sorted(positions) else 0.0
    constraint = list_f1(output.get("constraints", []), gold["constraints"])
    problem_similarity = SequenceMatcher(None, norm(output.get("problem", "")), norm(gold["problem"])).ratio()
    outcome_similarity = SequenceMatcher(None, norm(output.get("desired_outcome", "")), norm(gold["desired_outcome"])).ratio()
    score = (must["f1"] + flow_recall + order + constraint["recall"] + problem_similarity + outcome_similarity) / 6
    return {
        "must_have": must,
        "flow_recall": round(flow_recall, 4),
        "flow_order": order,
        "constraint_recall": constraint["recall"],
        "problem_similarity": round(problem_similarity, 4),
        "outcome_similarity": round(outcome_similarity, 4),
        "intent_fidelity_score": round(score, 4),
        "threshold_passed": score >= 0.8 and must["recall"] == 1.0 and order == 1.0,
    }


def build_core_payload(item: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    source = item["source"]
    assets, asset_sha256 = resolve_assets(source)
    return {
        "client_name": "Codex CLI Sales Intent Agent Evaluation",
        "project_name": source["name"],
        "industry": source["industry"],
        "scenario": item["raw_sales_brief"],
        "audience": extracted.get("primary_user") or extracted.get("actor") or "销售人员",
        "must_haves": extracted.get("must_haves", []),
        "boundaries": ["只交付本地静态演示"],
        "priority": "先完成可在浏览器中复核的核心销售演示",
        "acceptance_criteria": extracted.get("acceptance_criteria", []),
        "constraints": extracted.get("constraints", ["只交付本地静态演示", "不得连接外部服务"]),
        "intent_confirmed": True,
        "brand_tone": source.get("brand_tone", "清晰、克制、可验证"),
        "primary_color": source.get("primary_color", "#0071e3"),
        "provider": "codex_cli",
        "evaluation_mode": "core_generation",
        "evaluation_prompt_profile": "treatment-current",
        "evaluation_intent_profile": "intent-agent",
        "evaluation_case_id": source["id"],
        "evaluation_dataset": "codex-cli-v1",
        "evaluation_difficulty": source["difficulty"],
        "evaluation_intent": extracted.get("problem"),
        "evaluation_goal": extracted.get("desired_outcome"),
        "evaluation_flow_steps": extracted.get("flow_steps", []),
        "evaluation_method": extracted.get("acceptance_criteria", []),
        "evaluation_assets": assets,
        "evaluation_asset_sha256": asset_sha256,
        "evaluation_browser_contract": source.get("browser_contract", {}),
    }


async def extract(provider: CodexCliAgentProvider, item: dict[str, Any], trace_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trace_dir.mkdir(parents=True, exist_ok=True)
    output_path = trace_dir / "intent-output.json"
    if output_path.exists():
        cached = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict):
            raise ValueError(f"Recorded extraction is not an object: {output_path}")
        events_path = trace_dir / "intent-events.json"
        events = json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else []
        return cached, [*events, {"type": "process.reused", "path": str(output_path)}]
    source = item["source"]
    request = DemoRequest(
        client_name="Sales intent evaluator",
        project_name=source["name"],
        industry=source["industry"],
        scenario=item["raw_sales_brief"],
        audience="销售人员",
        provider="codex_cli",
        evaluation_case_id=source["id"],
        evaluation_intent_profile="raw-sales",
    )
    events: list[dict[str, Any]] = []
    inputs_path = ROOT / "testdata" / source["id"] / "inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    # The read-only provider prohibits tools: file paths alone are not context.
    # Embed authored input data, excluding acceptance paths and hidden assertions.
    input_data = {
        key: inputs[key]
        for key in ("schema_version", "case_id", "industry", "audience", "scenario", "fixtures", "assets")
        if key in inputs
    }
    if item.get("interview_input_policy") == "sales-text-only":
        # Prices/state transitions in ordinary fixtures must not pre-answer
        # the interview.  Core receives the common fixture later; the intent
        # module's initial context is only the salesperson's raw text.
        input_data = {}
    # Seller answers are deliberately withheld from turn 1.  The paired
    # experiment uses these frozen answers as the salesperson after the model
    # asks for clarification; putting them in the initial context would turn
    # the treatment into the old "already clarified brief" control.
    raw_answers = item.get("clarification_answers", [])
    clarification_answers: list[str] = []
    clarification_topics: list[str] = []
    for answer in raw_answers if isinstance(raw_answers, list) else []:
        if isinstance(answer, dict):
            text = answer.get("answer")
            topic = answer.get("question_topic")
            if isinstance(topic, str) and topic.strip():
                clarification_topics.append(topic.strip())
        else:
            text = answer
        if isinstance(text, str) and text.strip():
            clarification_answers.append(text.strip())
    context = {
        "intent_context": {
            "case_id": source["id"],
            "raw_sales_brief": item["raw_sales_brief"],
            "difficulty": source["difficulty"],
            "inputs_path": f"testdata/{source['id']}/inputs.json",
            "asset_root": f"testdata/{source['id']}/assets/",
            "gold_policy": "gold/intent-gold.json is evaluator-only and is not available to the intent agent",
        },
        "sales_brief": item["raw_sales_brief"],
        "input_data": input_data,
        "clarification_answers": [],
    }
    _write_json(trace_dir / "intent-request.json", request.model_dump())

    def save_event(event: dict[str, Any]) -> None:
        events.append(event)
        _write_json(trace_dir / "intent-events.json", events)

    async def run_turn(turn: int) -> dict[str, Any]:
        turn_output = trace_dir / f"intent-turn-{turn:02d}-output.json"
        if turn_output.exists():
            return json.loads(turn_output.read_text(encoding="utf-8"))
        _write_json(trace_dir / "intent-context.json", context)
        _write_json(trace_dir / f"intent-turn-{turn:02d}-context.json", context)
        prompt = _intent_prompt(request, context)
        (trace_dir / "intent-prompt.txt").write_text(prompt, encoding="utf-8")
        (trace_dir / f"intent-turn-{turn:02d}-prompt.txt").write_text(prompt, encoding="utf-8")
        result = await provider.run_agent("intent", request, context, on_event=save_event)
        _write_json(turn_output, result)
        return result

    try:
        result = await run_turn(1)
        if result.get("status") == "needs_clarification" and clarification_answers:
            topic_audit = _question_topic_audit(result, raw_answers)
            _write_json(trace_dir / "seller-question-audit.json", topic_audit)
            if topic_audit["missing_topics"]:
                result["_runner_interview_errors"] = [
                    "required seller topics were not covered by the model's clarification questions"
                ]
                _write_json(trace_dir / "seller-answers-withheld.json", {
                    "reason": "Model questions did not cover every required seller topic",
                    "missing_topics": topic_audit["missing_topics"],
                })
            else:
                # Release answers only after a real clarification request.
                # Keep turn 1's exact prompt/context untouched for replay.
                context["previous_intent"] = result
                context["clarification_answers"] = clarification_answers
                _write_json(trace_dir / "seller-answers-released.json", {
                    "released_after_turn": 1,
                    "question_topics": clarification_topics,
                    "answers": clarification_answers,
                    "script_sha256": item.get("clarification_script_sha256"),
                })
                result = await run_turn(2)
        elif result.get("status") == "needs_clarification":
            _write_json(trace_dir / "seller-answers-unavailable.json", {
                "reason": "No frozen seller clarification answers were configured",
            })
        elif clarification_answers and any(
            isinstance(item, dict) and item.get("required_before_core", False)
            for item in raw_answers
        ):
            # Do not let the runner stuff answers into a model that declared
            # ready without asking for the required seller topic.
            result["_runner_interview_errors"] = [
                "intent agent returned ready before asking required seller topics"
            ]
            _write_json(trace_dir / "seller-answers-withheld.json", {
                "reason": "Model returned ready without a required clarification turn",
            })
    except BaseException as exc:
        _write_json(trace_dir / "intent-extraction-error.json", {"type": type(exc).__name__, "message": str(exc)})
        raise
    _write_json(output_path, result)
    _write_json(trace_dir / "intent-events.json", events)
    return result, events


async def async_main(args: argparse.Namespace) -> int:
    selected, _ = load_intent_cases()
    if args.case_id:
        selected = [item for item in selected if item["id"] in set(args.case_id)]
    settings = Settings()
    provider = CodexCliAgentProvider(
        command=settings.codex_command,
        model=settings.codex_model,
        reasoning_effort=settings.codex_reasoning_effort,
        timeout_seconds=args.cli_timeout,
        cwd=ROOT,
    )
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    def save_report() -> None:
        _write_json(output_dir / "intent-agent-pilot.json", {
            "schema_version": "sales-intent-agent-pilot",
            "provider": "codex_cli",
            "real_intent_agent": True,
            "run_core": args.run_core,
            "case_ids": [row["case_id"] for row in rows],
            "rows": rows,
            "interpretation": "Gold scores are evaluator-only diagnostics, never the intent delivery gate. Core starts only for schema-valid ready output with no pending questions.",
        })

    with httpx.Client(timeout=60) as client:
        if args.run_core:
            health = client.get(f"{args.base_url.rstrip('/')}/api/health")
            health.raise_for_status()
        for item in selected:
            trace_dir = output_dir / item["id"]
            extracted, events = await extract(provider, item, trace_dir)
            row: dict[str, Any] = {
                "case_id": item["id"],
                "intent_output": extracted,
                "intent_process_events": [event.get("type") for event in events],
            }
            # Persist the raw output before scoring and the score before Core.
            rows.append(row)
            save_report()
            try:
                score = score_intent(extracted, item["gold"])
                row["intent_score"] = score
                _write_json(trace_dir / "intent-score-v2.json", score)
            except Exception as exc:
                row["intent_score_error"] = {"type": type(exc).__name__, "message": str(exc)}
                _write_json(trace_dir / "intent-score-error.json", row["intent_score_error"])
            row["intent_gate_errors"] = intent_gate_errors(extracted, item["id"])
            intent_gate = not row["intent_gate_errors"]
            row["intent_gate"] = "passed" if intent_gate else "failed"
            _write_json(trace_dir / "intent-case-result.json", row)
            save_report()
            if args.run_core and intent_gate:
                run_path = trace_dir / "core-run.json"
                if run_path.exists():
                    run_id = json.loads(run_path.read_text(encoding="utf-8"))["id"]
                else:
                    response = client.post(f"{args.base_url.rstrip('/')}/api/runs", json=build_core_payload(item, extracted))
                    response.raise_for_status()
                    run_id = response.json()["id"]
                    _write_json(run_path, {"id": run_id})
                row["core_run_id"] = run_id
                save_report()
                try:
                    run = wait_for_run(client, args.base_url.rstrip('/'), run_id, args.run_timeout)
                    row["core_result"] = compact_result(item["source"], run)
                except Exception as exc:
                    row["core_collection_error"] = {"type": type(exc).__name__, "message": str(exc)}
                    _write_json(trace_dir / "intent-case-result.json", row)
                    save_report()
                    raise
            elif args.run_core:
                row["core_skipped_reason"] = "intent_gate_failed"
            _write_json(trace_dir / "intent-case-result.json", row)
            save_report()
            print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cli-timeout", type=float, default=600)
    parser.add_argument("--run-timeout", type=float, default=1800)
    parser.add_argument("--run-core", action="store_true")
    args = parser.parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
