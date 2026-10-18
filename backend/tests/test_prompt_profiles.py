from pathlib import Path

from demopilot.core_loop import CoreBuilderLoop
from demopilot.models import DemoRequest, DemoRun


def _run(profile: str) -> DemoRun:
    return DemoRun(
        id=f"prompt-{profile}",
        request=DemoRequest(
            client_name="评测客户",
            project_name="结构化意图对照",
            industry="企业服务",
            scenario="运营人员需要处理一条带分支的业务记录。",
            audience="运营人员",
            must_haves=["记录列表", "状态分支"],
            provider="codex_cli",
            evaluation_case_id="medium-invoice-review-01",
            evaluation_dataset="codex-cli-v1",
            evaluation_mode="core_generation",
            evaluation_prompt_profile=profile,
            evaluation_difficulty="medium",
            evaluation_intent="把业务记录转成可追踪的处理流程。",
            evaluation_goal="用户能查看记录、处理分支并看到最终状态。",
            evaluation_flow_steps=["查看记录", "处理分支", "确认状态"],
            evaluation_method=["按四条浏览器旅程检查可见结果"],
        ),
    )


def test_control_and_treatment_render_distinct_prompt_headers(tmp_path: Path):
    loop = CoreBuilderLoop(None, None, project_root=tmp_path)  # type: ignore[arg-type]
    control = loop._goal_prompt(_run("control-legacy"), tmp_path, "medium-invoice-review-01", 0, [])
    treatment = loop._goal_prompt(_run("treatment-current"), tmp_path, "medium-invoice-review-01", 0, [])

    assert "Scenario:" in control
    assert "Intent:" not in control
    assert "Intent:" in treatment
    assert "Business flow:" in treatment
    common = "AUTHORITATIVE INPUTS AND ACCEPTANCE"
    assert common in control and common in treatment
    assert "WRITE PERMISSION (HARD BOUNDARY)" in control
    assert "WRITE PERMISSION (HARD BOUNDARY)" in treatment
