import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_sales_intent_agent_pilot as runner


def test_alias_substrings_score_supported_quote_features_and_penalize_discount():
    gold = ["套餐选择", "席位数量", "报价总额"]
    supported = ["支持选择一个套餐", "支持输入或选择席位数", "根据套餐和席位数即时显示演示报价"]
    assert runner.list_f1(supported, gold) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert runner.list_f1([*supported, "支持自定义优惠折扣"], gold) == {
        "precision": 0.75, "recall": 1.0, "f1": 0.8571,
    }


def _ready():
    return {
        "schema_version": "sales-intent-v2", "status": "ready", "case_id": "quote",
        "actor": "售前顾问", "problem": "展示报价", "desired_outcome": "看到报价",
        "must_haves": ["套餐选择"], "flow_steps": ["选择套餐"],
        "acceptance_criteria": ["页面显示报价"], "constraints": [], "non_goals": [],
        "assumptions": [], "questions": [], "confidence": 0.9,
        "traceability": [{"field": "must_haves", "source_quote": "选择套餐"}],
    }


def test_ready_delivery_gate_rejects_unresolved_questions_or_invalid_schema():
    output = _ready()
    assert runner.intent_gate_errors(output, "quote") == []
    output["questions"] = ["采用哪个定价规则？"]
    assert "unresolved questions remain" in runner.intent_gate_errors(output, "quote")
    output["questions"] = []
    output["must_haves"] = "套餐选择"
    assert any("must_haves" in item for item in runner.intent_gate_errors(output, "quote"))


def test_ready_intent_can_omit_unstated_order_but_not_business_capabilities():
    output = _ready()
    output["flow_steps"] = []
    assert runner.intent_gate_errors(output, "quote") == []
    output["must_haves"] = []
    assert "must_haves must not be empty" in runner.intent_gate_errors(output, "quote")
    output = _ready()
    output["flow_steps"] = None
    assert any("flow_steps" in error for error in runner.intent_gate_errors(output, "quote"))


def test_completed_extraction_is_reused_without_cli(tmp_path):
    output = _ready()
    path = tmp_path / "intent-output.json"
    path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()

    class ForbiddenProvider:
        async def run_agent(self, *args, **kwargs):
            raise AssertionError("A completed extraction must not call CLI again")

    result, events = asyncio.run(runner.extract(ForbiddenProvider(), {}, tmp_path))
    assert result == output
    assert events[-1]["type"] == "process.reused"
    assert path.read_bytes() == before


def test_failed_cli_retains_exact_prompt_fixture_context_and_events(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    inputs_path = tmp_path / "testdata" / "quote" / "inputs.json"
    inputs_path.parent.mkdir(parents=True)
    inputs_path.write_text(json.dumps({
        "case_id": "quote", "fixtures": {"price": 100},
        "paths": {"acceptance": "never-expose-acceptance.json"},
    }), encoding="utf-8")
    trace = tmp_path / "trace"

    class FailedProvider:
        async def run_agent(self, agent_id, request, context, on_event):
            assert context["input_data"]["fixtures"] == {"price": 100}
            on_event({"type": "process.started", "pid": 123})
            raise RuntimeError("test CLI interruption")

    item = {
        "source": {"id": "quote", "name": "Quote", "industry": "B2B", "difficulty": "simple"},
        "raw_sales_brief": "售前顾问选择套餐并展示报价", "gold": {"secret": "never-expose-gold"},
    }
    with pytest.raises(RuntimeError, match="test CLI interruption"):
        asyncio.run(runner.extract(FailedProvider(), item, trace))
    prompt = (trace / "intent-prompt.txt").read_text(encoding="utf-8")
    assert '"price": 100' in prompt
    assert "never-expose-acceptance" not in prompt
    assert "never-expose-gold" not in prompt
    assert "不要调用工具、不要读写文件" in prompt
    assert json.loads((trace / "intent-events.json").read_text(encoding="utf-8"))[0]["type"] == "process.started"
    assert json.loads((trace / "intent-extraction-error.json").read_text(encoding="utf-8"))["type"] == "RuntimeError"
