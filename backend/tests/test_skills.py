from __future__ import annotations

from demopilot.evaluation_models import EvaluationMetrics, EvaluationRequest, EvaluationRun
from demopilot.evaluator import _skill_promotion_decision
from demopilot.models import DemoRequest
from demopilot.prompts import build_agent_prompt
from demopilot.skill_runtime import SkillRegistry

EXPECTED_SKILLS = {
    "requirement-to-demo-spec",
    "vue-demo-engineering",
    "apple-ui-demo-design",
    "mock-business-data",
    "playwright-demo-acceptance",
    "targeted-demo-repair",
}


def demo_request() -> DemoRequest:
    return DemoRequest(
        client_name="测试客户",
        project_name="Skill 测试",
        industry="零售",
        scenario="区域经理需要筛选异常门店并创建跟进任务。",
        audience="区域经理",
        must_haves=["组合筛选", "创建任务"],
        provider="deepseek",
    )


def test_candidate_profile_contains_six_valid_versioned_skills():
    registry = SkillRegistry()
    profile = registry.describe_profile("candidate")

    assert set(profile["skill_names"]) == EXPECTED_SKILLS
    assert len(profile["bundle_sha256"]) == 64
    assert registry.describe_profile("baseline")["skill_names"] == []
    assert set(registry.describe_profile("approved")["skill_names"]) == EXPECTED_SKILLS


def test_progressive_routing_loads_only_stage_relevant_skills():
    registry = SkillRegistry()

    brief = registry.select("candidate", "brief")
    builder = registry.select("candidate", "builder")
    contract = registry.select("candidate", "contract")

    assert [item.name for item in brief] == ["requirement-to-demo-spec"]
    assert {item.name for item in builder} == {
        "vue-demo-engineering",
        "apple-ui-demo-design",
        "mock-business-data",
        "playwright-demo-acceptance",
        "targeted-demo-repair",
    }
    assert all(len(item.sha256) == 64 and item.content for item in builder)
    assert {item.name for item in contract} == {
        "requirement-to-demo-spec",
        "mock-business-data",
        "playwright-demo-acceptance",
    }


def test_skill_instructions_are_trusted_prompt_guidance_not_prior_result_data():
    registry = SkillRegistry()
    packet = registry.packet(registry.select("candidate", "brief"))

    prompt = build_agent_prompt(
        "brief",
        demo_request(),
        {"__engineering_skills__": packet},
    )

    assert "可信工程 Skill" in prompt
    assert "requirement-to-demo-spec" in prompt
    assert '"__engineering_skills__"' not in prompt


def test_skill_promotion_requires_measured_first_pass_improvement_without_regression():
    baseline = EvaluationRun(
        id="baseline",
        request=EvaluationRequest(
            provider="deepseek",
            case_ids=["retail-01"],
            case_limit=1,
            skill_profile="baseline",
            first_pass_only=True,
        ),
        case_ids=["retail-01"],
        status="completed",
        metrics=EvaluationMetrics(
            total_cases=1,
            completed_cases=1,
            first_pass_success_rate=0,
            first_pass_average_score=72,
            browser_pass_rate=0,
            feature_coverage_rate=1,
            average_agent_calls=8,
        ),
    )
    candidate = EvaluationRun(
        id="candidate",
        request=EvaluationRequest(
            provider="deepseek",
            case_ids=["retail-01"],
            case_limit=1,
            skill_profile="candidate",
            first_pass_only=True,
        ),
        case_ids=["retail-01"],
        status="completed",
        metrics=EvaluationMetrics(
            total_cases=1,
            completed_cases=1,
            first_pass_success_rate=1,
            first_pass_average_score=95,
            browser_pass_rate=1,
            feature_coverage_rate=1,
            average_agent_calls=8,
        ),
    )

    decision = _skill_promotion_decision(candidate, baseline)

    assert decision["eligible"] is True
    candidate.metrics.average_agent_calls = 9
    assert _skill_promotion_decision(candidate, baseline)["eligible"] is False
