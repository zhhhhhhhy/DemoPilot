import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_sales_intent_agent_pilot as intent_runner
import run_sales_intent_paired_real as runner


def _case_files(tmp_path):
    folder = tmp_path / "testdata" / "quote"
    folder.mkdir(parents=True)
    contract = {
        "case_id": "quote", "schema_version": "core-acceptance-v2",
        "intent": "secret-intent", "goal": "secret-goal", "flow_steps": ["secret-flow"],
        "expected_result": ["secret-result"], "evaluation_method": ["secret-method"],
        "controls": {"#total": "visible quote"},
        "tests": [{"id": "pricing", "steps": [{"action": "click", "selector": "#calculate", "value": "",
            "assertions": {"#total": {"contains": ["secret-answer"]}}}]}],
    }
    inputs = {"case_id": "quote", "industry": "B2B", "audience": "secret-audience",
              "scenario": "secret-complete-scenario", "fixtures": {"price": 100},
              "paths": {"gold": "secret-gold", "acceptance": "secret-acceptance"}}
    for filename, value in (("acceptance.json", contract), ("inputs.json", inputs)):
        (folder / filename).write_text(json.dumps(value), encoding="utf-8")
    return folder, {path.name: path.read_bytes() for path in folder.iterdir()}


def test_mask_hides_answers_and_restores_on_cancellation(tmp_path):
    folder, originals = _case_files(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        with runner.masked_model_files(tmp_path, "quote"):
            model_contract = (folder / "acceptance.json").read_text()
            assert "secret-" not in model_contract
            assert '"action": "click"' in model_contract
            assert "secret-" not in (folder / "inputs.json").read_text()
            raise asyncio.CancelledError()
    assert all((folder / name).read_bytes() == content for name, content in originals.items())


def test_masked_inputs_keep_common_fixture_but_hide_duplicate_intent(tmp_path):
    folder, _ = _case_files(tmp_path)
    with runner.masked_model_files(tmp_path, "quote"):
        visible = json.loads((folder / "inputs.json").read_text(encoding="utf-8"))
        assert visible["case_id"] == "quote"
        assert visible["industry"] == "B2B"
        assert visible["fixtures"] == {"price": 100}
        assert "scenario" not in visible
        assert "audience" not in visible


def test_tampering_restores_originals_and_fails_closed(tmp_path):
    folder, originals = _case_files(tmp_path)
    with pytest.raises(RuntimeError, match="modified protected redacted"):
        with runner.masked_model_files(tmp_path, "quote"):
            (folder / "acceptance.json").write_text("{}")
    assert all((folder / name).read_bytes() == content for name, content in originals.items())


def test_both_builder_and_acceptance_child_receive_only_masked_contract(tmp_path, monkeypatch):
    folder, originals = _case_files(tmp_path)
    observations = []

    async def fake(self, **kwargs):
        observations.append(json.loads((folder / "acceptance.json").read_text()))
        assert "EXPERIMENT INPUT BOUNDARY" in kwargs["prompt"]
        return {"acceptance_command_passed": True}

    monkeypatch.setattr(runner.CodexCliHarness, "build", fake)
    monkeypatch.setattr(runner.CodexCliHarness, "acceptance_check", fake)
    harness = runner.HiddenAnswerHarness(object(), "quote")
    asyncio.run(harness.build(workspace=tmp_path, prompt="build"))
    asyncio.run(harness.acceptance_check(workspace=tmp_path, prompt="check"))
    assert len(observations) == 2
    assert all("assertions" not in record["tests"][0]["steps"][0] for record in observations)
    assert all((folder / name).read_bytes() == content for name, content in originals.items())


def test_final_metrics_include_blocked_case_and_intent_overhead():
    common = {"case_id": "quote", "revision_count": 0, "agent_calls": 2}
    control = {**common, "arm": "raw-sales", "final_pass": True, "total_cli_calls": 2, "intent_cli_calls": 0}
    treatment = {**common, "arm": "intent-agent", "final_pass": False, "total_cli_calls": 1, "intent_cli_calls": 1}
    summary = runner.summarize([control, treatment], ["quote"])
    assert summary["all_selected_terminal"] is True
    assert summary["arms"]["intent-agent"]["final_pass_rate"] == "0/1"
    assert summary["arms"]["intent-agent"]["intent_cli_calls"] == 1
    assert summary["observed_improvement"] is False
    assert runner.final_pass({"publication_status": "published"}) is False


def test_true_experiment_uses_exact_raw_sentence_and_frozen_seller_script():
    cases = runner.load_experiment_cases()
    authored = json.loads(
        (runner.ROOT / "evaluation_sets/sales-intent-v1/cases.json").read_text(encoding="utf-8")
    )
    authored_by_id = {item["id"]: item for item in authored["cases"]}
    assert cases
    for item in cases:
        # No goal/flow/acceptance/answer text is appended to the baseline.
        assert item["raw_sales_brief"] == authored_by_id[item["id"]]["raw_sales_brief"]
        assert "销售补充" not in item["raw_sales_brief"]
        assert item["clarification_answers"]
        assert all(isinstance(answer, dict) for answer in item["clarification_answers"])
        control = runner.core_request(item, "raw-sales")
        assert control.intent_confirmed is False
        assert control.must_haves == []
        assert control.acceptance_criteria == []
        treatment = runner.core_request(item, "intent-agent", _intent_ready(item["id"]))
        assert treatment.intent_confirmed is True
        assert treatment.must_haves


def _intent_ready(case_id: str):
    return {
        "actor": "销售人员",
        "problem": "需要完成销售演示",
        "desired_outcome": "客户可以看到结果",
        "must_haves": ["核心演示能力"],
        "flow_steps": ["完成演示"],
        "acceptance_criteria": ["页面出现可见结果"],
        "constraints": ["只做本地演示"],
        "case_id": case_id,
    }


def test_answers_are_released_only_after_needs_clarification(tmp_path, monkeypatch):
    monkeypatch.setattr(intent_runner, "ROOT", tmp_path)
    input_path = tmp_path / "testdata" / "quote" / "inputs.json"
    input_path.parent.mkdir(parents=True)
    input_path.write_text(
        json.dumps({"case_id": "quote", "fixtures": {"price": 100}}), encoding="utf-8"
    )
    seen_contexts = []

    class InterviewProvider:
        def __init__(self):
            self.calls = 0

        async def run_agent(self, agent_id, request, context, on_event):
            self.calls += 1
            seen_contexts.append(json.loads(json.dumps(context)))
            on_event({"type": "process.started", "pid": self.calls})
            if self.calls == 1:
                return {
                    "status": "needs_clarification",
                    "questions": ["采用什么报价规则？"],
                }
            return {
                "status": "ready",
                "questions": [],
                "schema_version": "sales-intent-v2",
                "case_id": "quote",
            }

    item = {
        "source": {
            "id": "quote", "name": "Quote", "industry": "B2B", "difficulty": "simple"
        },
        "raw_sales_brief": "售前顾问选择套餐并展示报价",
        "interview_input_policy": "sales-text-only",
        "clarification_answers": [{
            "question_topic": "报价规则",
            "answer": "基础套餐每席位 100，折扣为 0。",
        }],
        "clarification_script_sha256": "script-sha",
    }
    trace = tmp_path / "trace"
    result, events = asyncio.run(runner.extract(InterviewProvider(), item, trace))
    assert result["status"] == "ready"
    assert len(seen_contexts) == 2
    assert seen_contexts[0]["input_data"] == {}
    assert seen_contexts[0]["clarification_answers"] == []
    assert seen_contexts[1]["clarification_answers"] == ["基础套餐每席位 100，折扣为 0。"]
    first_prompt = (trace / "intent-turn-01-prompt.txt").read_text(encoding="utf-8")
    second_prompt = (trace / "intent-turn-02-prompt.txt").read_text(encoding="utf-8")
    assert "基础套餐每席位 100" not in first_prompt
    assert "基础套餐每席位 100" in second_prompt
    released = json.loads((trace / "seller-answers-released.json").read_text(encoding="utf-8"))
    assert released["released_after_turn"] == 1
