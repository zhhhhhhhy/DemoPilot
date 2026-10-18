from demopilot.models import DemoRequest
from demopilot.prompts import build_agent_prompt


def test_intent_agent_prompt_requires_typed_sales_intent() -> None:
    request = DemoRequest(
        client_name="Sales",
        project_name="Quote",
        industry="B2B",
        scenario="客户希望在演示中快速看到报价。",
        audience="销售",
    )
    prompt = build_agent_prompt("intent", request, {})
    assert "must_haves" in prompt
    assert "flow_steps" in prompt
    assert "questions" in prompt
    assert "confidence" in prompt


def test_intent_agent_prompt_defines_context_goal_and_boundaries() -> None:
    request = DemoRequest(
        client_name="Sales",
        project_name="Quote",
        industry="B2B",
        scenario="客户希望在演示中快速看到报价。",
        audience="销售",
        evaluation_case_id="simple-quote-generator-01",
    )
    prompt = build_agent_prompt(
        "intent",
        request,
        {
            "intent_context": {
                "case_id": "simple-quote-generator-01",
                "inputs_path": "testdata/simple-quote-generator-01/inputs.json",
                "gold_policy": "gold is evaluator-only",
            }
        },
    )
    assert "inputs.json" in prompt
    assert "gold/intent-gold.json" in prompt
    assert "needs_clarification" in prompt
    assert "source_quote" in prompt
    assert "禁止增加原话没有的功能" in prompt
