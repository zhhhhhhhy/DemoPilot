from __future__ import annotations

from demopilot.builder_preflight import preflight_builder_output
from demopilot.interaction_contract import compile_interaction_contract, contract_tests
from demopilot.models import DemoRequest, DemoRun


def request() -> DemoRequest:
    return DemoRequest(
        client_name="契约客户",
        project_name="契约测试",
        industry="供应链",
        scenario="用户需要筛选异常并创建任务。",
        audience="运营负责人",
        must_haves=["异常筛选", "创建任务"],
        provider="mock",
    )


def test_compiler_owns_selectors_and_covers_requirements_exactly():
    raw = {
        "requirements": [
            {
                "requirement": "异常筛选",
                "screen": "异常中心",
                "steps": [
                    {
                        "action": "select",
                        "selector": "#model-invented-selector",
                        "value": "高风险",
                        "purpose": "选择风险等级",
                    }
                ],
                "assertion": {"text_contains": ["仅显示高风险"]},
            },
            {
                "requirement": "创建任务",
                "screen": "任务中心",
                "steps": [
                    {"action": "fill", "value": "李雷", "purpose": "填写负责人"},
                    {"action": "click", "purpose": "提交任务"},
                ],
                "assertion": {"text_contains": ["任务创建成功"]},
            },
        ]
    }

    contract = compile_interaction_contract(request(), raw)
    tests = contract_tests(contract)

    assert contract["frozen"] is True
    assert len(contract["contract_sha256"]) == 64
    assert [item["requirement"] for item in tests] == request().must_haves
    assert tests[0]["steps"][0]["selector"] == "#contract-nav-1"
    assert tests[0]["steps"][1]["selector"] == "#contract-1-step-1"
    assert "model-invented-selector" not in str(contract)
    assert tests[1]["assertion"]["selector"] == "#contract-2-result"


def test_compiler_supplies_safe_default_for_missing_model_requirement():
    contract = compile_interaction_contract(
        request(),
        {"requirements": [{"requirement": "异常筛选", "steps": []}]},
    )

    assert contract["coverage"]["missing"] == []
    assert len(contract_tests(contract)) == 2
    assert any("创建任务" in warning for warning in contract["normalization_warnings"])


def test_compiler_normalizes_descriptive_assertions_to_atomic_visible_terms():
    contract = compile_interaction_contract(
        request(),
        {
            "requirements": [
                {
                    "requirement": "异常筛选",
                    "assertion": {
                        "text_contains": [
                            "页面显示筛选结果数量及门店列表，包含高缺货量门店。"
                        ]
                    },
                },
                {
                    "requirement": "创建任务",
                    "assertion": {"text_contains": ["任务创建成功"]},
                },
            ]
        },
    )

    assert contract["version"] == "interaction-contract-v1.1"
    assert contract_tests(contract)[0]["assertion"]["text_contains"] == [
        "筛选结果数量及门店列表",
        "高缺货量门店",
    ]


def valid_builder_files() -> dict[str, str]:
    return {
        "demo/index.html": """<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="styles.css"></head><body>
<p>演示数据，未连接客户生产系统</p>
<button id="advanceButton" class="nav-item">推进</button>
<button id="contract-nav-1">异常筛选</button><section id="contract-view-1">
<select id="contract-1-step-1"><option>高风险</option></select>
<div id="contract-1-result">等待操作</div></section>
<button id="contract-nav-2">创建任务</button><section id="contract-view-2">
<input id="contract-2-step-1"><button id="contract-2-step-2">提交</button>
<div id="contract-2-result">等待操作</div></section>
<script src="app.js"></script></body></html>""",
        "demo/styles.css": ":root { --accent: #0071e3; }",
        "demo/app.js": """const data = {"story":["发现异常","处理异常","复核结果"],"features":["异常筛选","创建任务"]}; let current = 0;
document.querySelector('#advanceButton').addEventListener('click', () => { current += 1; });
const messages = ['仅显示高风险', '任务创建成功'];
""",
    }


def test_builder_preflight_passes_only_objective_contract_checks():
    demo_request = request()
    run = DemoRun(id="preflight-pass", request=demo_request)
    raw = {
        "requirements": [
            {
                "requirement": "异常筛选",
                "steps": [{"action": "select", "value": "高风险"}],
                "assertion": {"text_contains": ["仅显示高风险"]},
            },
            {
                "requirement": "创建任务",
                "steps": [
                    {"action": "fill", "value": "李雷"},
                    {"action": "click"},
                ],
                "assertion": {"text_contains": ["任务创建成功"]},
            },
        ]
    }
    run.outputs["interaction_contract"] = compile_interaction_contract(demo_request, raw)
    run.outputs["builder"] = {"files": valid_builder_files()}

    result = preflight_builder_output(run)

    assert result["status"] == "passed"
    assert result["blocking"] is False
    assert result["issues"] == []
    assert "visual_taste" in result["scope"]["soft_reviewer_only"]


def test_builder_preflight_reports_security_and_exact_missing_selectors():
    demo_request = request()
    run = DemoRun(id="preflight-fail", request=demo_request)
    run.outputs["interaction_contract"] = compile_interaction_contract(demo_request, {})
    files = valid_builder_files()
    files["demo/index.html"] = files["demo/index.html"].replace(
        ' id="contract-2-step-1"', ""
    )
    files["demo/app.js"] += "\ndocument.body.innerHTML = '<p>unsafe</p>';"
    run.outputs["builder"] = {"files": files}

    result = preflight_builder_output(run)

    assert result["status"] == "failed"
    assert {"security", "selector"}.issubset(result["failure_classes"])
    selector_issue = next(
        item for item in result["issues"] if item["code"] == "CONTRACT_SELECTORS_MISSING"
    )
    assert "#contract-2-step-1" in selector_issue["selectors"]
