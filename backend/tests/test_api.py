from __future__ import annotations

import asyncio
import json
import time
import zipfile

from fastapi.testclient import TestClient

from demopilot.config import Settings
from demopilot.generator import generate_artifacts
from demopilot.harness import SandboxViolation, SandboxWorkspace
from demopilot.interaction_contract import compile_interaction_contract
from demopilot.main import create_app
from demopilot.models import DemoRequest, DemoRun
from demopilot.orchestrator import DemoOrchestrator
from demopilot.providers.mock import MockAgentProvider
from demopilot.reviewer import default_review_rubric, normalize_final_review
from demopilot.runtime import RunManager
from demopilot.storage import RunStore
from demopilot.verifier import verify_artifacts


def make_client(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path / "data")))


def payload(**overrides):
    base = {
        "client_name": "远山科技",
        "project_name": "智能运营指挥台",
        "industry": "企业服务",
        "scenario": "运营团队每天需要在多个系统之间切换，无法快速判断优先级并追踪结果。",
        "audience": "运营负责人",
        "must_haves": ["运营总览", "任务分派", "效果复盘"],
        "brand_tone": "简洁、可信、现代",
        "primary_color": "#0071e3",
        "provider": "mock",
    }
    base.update(overrides)
    return base


def wait_for_status(client, run_id, expected, *, timeout=30):
    expected_values = {expected} if isinstance(expected, str) else set(expected)
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.get(f"/api/runs/{run_id}").json()
        if last["status"] in expected_values:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run did not reach {expected_values}; last={last}")


def test_request_defaults_to_deepseek():
    request_payload = payload()
    request_payload.pop("provider")
    assert DemoRequest(**request_payload).provider == "deepseek"


def test_health_and_templates(tmp_path):
    with make_client(tmp_path) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        templates = client.get("/api/templates")
        assert templates.status_code == 200
        assert len(templates.json()) == 3


def test_run_completes_and_artifacts_download(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/runs", json=payload())
        assert response.status_code == 202
        run_id = response.json()["id"]
        run = wait_for_status(client, run_id, "completed")
        assert run["status"] == "completed"
        assert run["progress"] == 100
        assert len(run["events"]) == 22
        assert run["outputs"]["builder_preflight"]["status"] == "skipped"
        assert any(event["event_type"] == "gate" for event in run["events"])
        assert run["agent_calls"] == 9
        assert run["revision_count"] == 0
        assert run["quality_gate"] == "passed"
        assert run["outputs"]["artifact_validation"]["status"] == "passed"
        assert run["outputs"]["artifact_validation"]["browser_e2e"]["status"] == "passed"
        assert run["outputs"]["artifact_validation"]["shared_contract"]["status"] == "passed"
        assert len(run["outputs"]["interaction_contract"]["contract_sha256"]) == 64
        assert run["outputs"]["interaction_contract"]["frozen"] is True
        assert run["outputs"]["build_provenance"]["source_mode"] == "controlled_template_fallback"
        assert len(run["tool_receipts"]) >= 18
        assert all(
            receipt["sha256"]
            for receipt in run["tool_receipts"]
            if receipt["action"] in {"write", "archive"} and receipt["status"] == "succeeded"
        )
        event_ids = [event["agent_id"] for event in run["events"]]
        assert event_ids.index("runner") < event_ids.index("reviewer", event_ids.index("runner"))
        product_started = next(
            index
            for index, event in enumerate(run["events"])
            if event["agent_id"] == "product" and event["status"] == "running"
        )
        experience_started = next(
            index
            for index, event in enumerate(run["events"])
            if event["agent_id"] == "experience" and event["status"] == "running"
        )
        first_parallel_done = next(
            index
            for index, event in enumerate(run["events"])
            if event["agent_id"] in {"product", "experience"}
            and event["status"] == "completed"
        )
        assert product_started < first_parallel_done
        assert experience_started < first_parallel_done
        assert {"demo", "spec", "script", "qa", "archive"}.issubset({
            item["kind"] for item in run["artifacts"]
        })
        demo = client.get(f"/api/runs/{run_id}/files/artifacts/demo/index.html")
        assert demo.status_code == 200
        assert "智能运营指挥台" in demo.text
        archive = client.get(f"/api/runs/{run_id}/files/{run_id}-demo-package.zip")
        assert archive.status_code == 200
        archive_path = tmp_path / "demo.zip"
        archive_path.write_bytes(archive.content)
        with zipfile.ZipFile(archive_path) as bundle:
            assert "demo/index.html" in bundle.namelist()
            spec = json.loads(bundle.read("demo-spec.json").decode("utf-8"))
        assert spec["meta"]["data_mode"] == "controlled_fixture"
        assert run["outputs"]["review_rubric"]["total_weight"] == 100
        review = run["outputs"]["reviewer"]
        assert review["decision"] == "pass"
        assert review["overall_score"] == 98
        assert review["evidence"]["browser_status"] == "passed"
        assert review["evidence"]["source_mode"] == "controlled_template_fallback"
        assert review["issues"] == []
        assert review["open_gates"] == []
        assert "业务数据使用本地虚构样例" in review["scope_boundaries"]
        assert review["simulated_features"] == payload()["must_haves"]
        assert "导航高亮切换" in review["real_features"]
        report = client.get(f"/api/runs/{run_id}/files/artifacts/qa-report.md")
        assert "Reviewer 独立评审报告" in report.text
        assert "需求覆盖" in report.text


def test_customer_text_is_escaped_in_html(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/runs",
            json=payload(
                client_name="测试<script>alert(1)</script>",
                project_name="安全演示",
            ),
        )
        run_id = response.json()["id"]
        wait_for_status(client, run_id, "completed")
        page = client.get(f"/api/runs/{run_id}/files/artifacts/demo/index.html")
        assert "<script>alert(1)</script>" not in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_claude_mode_requires_explicit_enablement(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/runs", json=payload(provider="claude"))
        assert response.status_code == 400


class RevisionOnceProvider(MockAgentProvider):
    def __init__(self):
        self.qa_calls = 0

    async def run_agent(self, agent_id, request, context, *, iteration=0):
        result = await super().run_agent(
            agent_id, request, context, iteration=iteration
        )
        if agent_id == "reviewer" and context.get("review_phase", {}).get("mode") != "rubric":
            self.qa_calls += 1
            if self.qa_calls == 1:
                return {
                    **result,
                    "status": "revision_required",
                    "decision": "revise",
                    "issues": ["需要一次受控返工测试"],
                }
        return result


class UnsafeFirstBuilderProvider(MockAgentProvider):
    async def run_agent(self, agent_id, request, context, *, iteration=0):
        result = await super().run_agent(agent_id, request, context, iteration=iteration)
        if agent_id == "builder" and iteration == 0:
            return {
                **result,
                "deliverables": [
                    "demo/index.html",
                    "demo/styles.css",
                    "demo/app.js",
                ],
                "files": {
                    "demo/index.html": (
                        '<!doctype html><html><head><link rel="stylesheet" '
                        'href="styles.css"></head><body><script src="app.js"></script>'
                        "</body></html>"
                    ),
                    "demo/styles.css": ":root { --primary: #0071e3; }",
                    "demo/app.js": "document.body.innerHTML = '<p>unsafe</p>';",
                },
            }
        return result


class UnsafeRevisionBuilderProvider(RevisionOnceProvider):
    async def run_agent(self, agent_id, request, context, *, iteration=0):
        result = await super().run_agent(agent_id, request, context, iteration=iteration)
        if agent_id == "builder" and iteration == 1:
            return {
                **result,
                "files": {
                    "demo/index.html": (
                        '<!doctype html><html><head><link rel="stylesheet" '
                        'href="styles.css"></head><body><script src="app.js"></script>'
                        "</body></html>"
                    ),
                    "demo/styles.css": ":root { --primary: #0071e3; }",
                    "demo/app.js": "document.body.innerHTML = '<p>unsafe revision</p>';",
                },
            }
        return result


def test_qa_can_send_builder_through_one_revision(tmp_path):
    store = RunStore(tmp_path / "data")
    request = DemoRequest.model_validate(payload())
    run = DemoRun(id="abcdef123456", request=request)
    store.create(run)
    orchestrator = DemoOrchestrator(
        store,
        {"mock": RevisionOnceProvider()},
        max_agent_calls=12,
        max_revision_rounds=1,
        max_parallel_agents=2,
    )

    asyncio.run(orchestrator.execute(run.id))

    completed = store.get(run.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.revision_count == 1
    assert completed.agent_calls == 11
    assert "builder_iteration_1" in completed.outputs
    assert "reviewer_iteration_1" in completed.outputs
    assert completed.outputs["reviewer"]["decision"] == "pass"
    first_review = completed.outputs["reviewer_iteration_0"]
    assert first_review["decision"] == "revise"
    assert first_review["issues"][0]["root_cause"]
    assert first_review["issues"][0]["verification"]


def test_unsafe_builder_is_blocked_by_preflight_and_recovers_before_write(tmp_path):
    store = RunStore(tmp_path / "data")
    request = DemoRequest.model_validate(payload())
    run = DemoRun(id="abcdef654321", request=request)
    store.create(run)
    orchestrator = DemoOrchestrator(
        store,
        {"mock": UnsafeFirstBuilderProvider()},
        max_agent_calls=12,
        max_revision_rounds=1,
        max_parallel_agents=2,
    )

    asyncio.run(orchestrator.execute(run.id))

    completed = store.get(run.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.revision_count == 1
    failed_preflight = completed.outputs["builder_preflight_iteration_0"]
    assert failed_preflight["status"] == "failed"
    assert "security" in failed_preflight["failure_classes"]
    assert "artifact_validation_iteration_0" not in completed.outputs
    assert "reviewer_iteration_0" not in completed.outputs
    assert completed.outputs["artifact_validation_iteration_1"]["status"] == "passed"
    assert all(receipt.status != "failed" for receipt in completed.tool_receipts)


def test_every_reviewer_revision_reenters_builder_preflight(tmp_path):
    store = RunStore(tmp_path / "data")
    request = DemoRequest.model_validate(payload())
    run = DemoRun(id="a1b2c3d4e5f6", request=request)
    store.create(run)
    orchestrator = DemoOrchestrator(
        store,
        {"mock": UnsafeRevisionBuilderProvider()},
        max_agent_calls=14,
        max_revision_rounds=2,
        max_parallel_agents=2,
    )

    asyncio.run(orchestrator.execute(run.id))

    completed = store.get(run.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.revision_count == 2
    assert completed.outputs["builder_preflight_iteration_1"]["status"] == "failed"
    assert "security" in completed.outputs["builder_preflight_iteration_1"]["failure_classes"]
    assert completed.outputs["builder_preflight_iteration_2"]["status"] == "skipped"
    assert "artifact_validation_iteration_1" not in completed.outputs
    assert "reviewer_iteration_1" not in completed.outputs


def test_manager_accepts_provider_workstream_parallel_shape():
    manager_result = {
        "parallel_groups": [
            {"id": "parallel-1", "workstreams": ["ws-product", "ws-design"]}
        ]
    }
    assert DemoOrchestrator._approved_parallel_design(manager_result) is True


def test_agent_context_excludes_duplicate_history_and_previous_source_files(tmp_path):
    request = DemoRequest.model_validate(payload())
    run = DemoRun(id="context123456", request=request)
    run.outputs = {
        "brief": {"goal": "演示"},
        "manager": {"objective": "交付"},
        "discovery": {"problem_statement": "异常"},
        "product": {"demo_story": ["一", "二", "三"]},
        "experience": {"visual_direction": "Apple-like"},
        "review_rubric": {"criteria": ["覆盖需求"]},
        "builder": {
            "implementation": "第一版",
            "files": {"demo/app.js": "x" * 50_000},
        },
        "builder_iteration_0": {"files": {"demo/app.js": "x" * 50_000}},
        "revision_feedback": {"artifact_validation": {"issues": ["修复契约"]}},
        "artifact_validation": {"status": "failed"},
        "qa": {"decision": "revise"},
        "qa_iteration_0": {"decision": "revise"},
    }

    builder_context = DemoOrchestrator._context_for_agent(run, "builder", iteration=1)
    reviewer_context = DemoOrchestrator._context_for_agent(run, "reviewer", phase="final")

    assert "files" not in builder_context["previous_builder_summary"]
    assert "builder_iteration_0" not in builder_context
    assert "qa" not in builder_context
    assert reviewer_context["builder"]["files"]["demo/app.js"]
    assert "builder_iteration_0" not in reviewer_context
    assert "qa_iteration_0" not in reviewer_context


def test_reviewer_evidence_issue_changes_coverage_and_score():
    request = DemoRequest.model_validate(payload())
    validation = {
        "status": "passed",
        "source_mode": "agent_generated_files",
        "checks": ["基础文件与固定交互通过"],
        "issues": [],
        "feature_coverage": {
            "required": request.must_haves,
            "rendered": request.must_haves,
            "missing": [],
        },
        "browser_e2e": {"status": "passed", "evidence": "/evidence.png"},
        "fixed_contract": {"supported_interactions": ["导航高亮切换"]},
        "manifest": [],
    }
    model_review = {
        "decision": "revise",
        "dimension_scores": {"demo_clarity": 15},
        "issues": [
            {
                "id": "REQ-1",
                "severity": "critical",
                "category": "requirement_coverage",
                "requirement": request.must_haves[0],
                "evidence": f"{request.must_haves[0]}只有文字标签，没有业务模块",
                "root_cause": "关键词检查替代了模块检查",
                "repair_instruction": "增加可识别模块和前端交互",
                "verification": "在 Chromium 中操作该模块",
            }
        ],
        "open_gates": [],
    }
    review = normalize_final_review(
        request,
        model_review,
        validation,
        default_review_rubric(request),
    )

    assert review["decision"] == "revise"
    assert review["overall_score"] < 80
    assert review["requirement_coverage"][0]["status"] == "insufficient"
    assert review["score_adjustments"]


def test_reviewer_treats_static_demo_non_goals_as_completed_scope():
    request = DemoRequest.model_validate(payload())
    validation = {
        "status": "passed",
        "source_mode": "agent_generated_files",
        "checks": ["基础文件与固定交互通过"],
        "issues": [],
        "feature_coverage": {
            "required": request.must_haves,
            "rendered": request.must_haves,
            "missing": [],
        },
        "browser_e2e": {"status": "passed", "evidence": "/evidence.png"},
        "fixed_contract": {"supported_interactions": ["导航高亮切换"]},
        "manifest": [],
    }
    review = normalize_final_review(
        request,
        {
            "decision": "pass_with_open_gates",
            "dimension_scores": {
                "requirement_coverage": 24,
                "interaction": 19,
                "artifact": 15,
                "safety": 15,
                "demo_clarity": 12,
                "provenance": 10,
            },
            "issues": [],
            "open_gates": [
                "真实 ERP/WMS 系统集成",
                "生产鉴权与部署",
                "客户明确要求但尚未展示的批量导出交互",
            ],
        },
        validation,
        default_review_rubric(request),
    )

    assert review["decision"] == "pass_with_open_gates"
    assert review["open_gates"] == ["客户明确要求但尚未展示的批量导出交互"]
    assert all("ERP" not in item for item in review["open_gates"])
    assert review["scope_boundaries"]


def test_generator_normalizes_nested_story_and_verifies_contract(tmp_path):
    request = DemoRequest.model_validate(payload())
    run = DemoRun(id="123456abcdef", request=request)
    run.outputs["product"] = {
        "features": request.must_haves,
        "demo_story": {
            "title": "领域故事",
            "act_1": {"title": "发现高风险任务"},
            "act_2": {"title": "完成任务分派"},
            "act_3": {"title": "复核业务结果"},
        },
    }
    run.outputs["interaction_contract"] = compile_interaction_contract(request, {})
    generate_artifacts(run, tmp_path)
    validation = verify_artifacts(run, tmp_path)
    app_js = (tmp_path / "artifacts" / "demo" / "app.js").read_text(encoding="utf-8")

    assert validation["status"] == "passed"
    assert validation["feature_coverage"]["missing"] == []
    assert "发现高风险任务" in app_js
    assert "[object Object]" not in app_js


def test_sandbox_blocks_path_escape_and_secret(tmp_path):
    request = DemoRequest.model_validate(payload())
    run = DemoRun(id="abcabc123123", request=request)
    workspace = SandboxWorkspace(run, tmp_path)

    try:
        workspace.write_text("../outside.html", "safe")
    except SandboxViolation:
        pass
    else:
        raise AssertionError("path traversal should be rejected")

    try:
        workspace.write_text("artifacts/demo/app.js", "const apiKey = 'sk-1234567890abcdefgh';")
    except SandboxViolation:
        pass
    else:
        raise AssertionError("secret-like content should be rejected")

    assert len(run.tool_receipts) == 2
    assert all(receipt.status == "failed" for receipt in run.tool_receipts)
    assert not (tmp_path.parent / "outside.html").exists()

    workspace.write_text(
        "artifacts/demo/safe.js",
        "[1, 2].map(function(value) { return value * 2; });",
    )
    assert run.tool_receipts[-1].status == "succeeded"

    workspace.write_text(
        "artifacts/demo/empty-clear.js",
        "container.innerHTML = ''; container.replaceChildren();",
    )
    assert run.tool_receipts[-1].status == "succeeded"

    try:
        workspace.write_text(
            "artifacts/demo/html-injection.js",
            "container.innerHTML = '<img src=x>';")
    except SandboxViolation:
        pass
    else:
        raise AssertionError("non-empty innerHTML should be rejected")

    try:
        workspace.write_text("artifacts/demo/unsafe.js", "new Function('return 1')();")
    except SandboxViolation:
        pass
    else:
        raise AssertionError("dynamic Function construction should be rejected")


def test_manual_approval_pauses_then_completes_and_sse_replays(tmp_path):
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/runs",
            json=payload(require_execution_approval=True),
        )
        run_id = created.json()["id"]
        waiting = wait_for_status(client, run_id, "waiting_approval")
        assert waiting["status"] == "waiting_approval"
        assert waiting["tool_receipts"] == []
        approval = next(item for item in waiting["approvals"] if item["status"] == "pending")

        decided = client.post(
            f"/api/runs/{run_id}/approvals/{approval['id']}",
            json={"decision": "approve"},
        )
        assert decided.status_code == 200
        completed = wait_for_status(client, run_id, "completed")
        assert completed["status"] == "completed"
        assert completed["approvals"][0]["status"] == "approved"
        assert completed["tool_receipts"]

        with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
            body = "".join(stream.iter_text())
        assert "event: run" in body
        assert '"status":"completed"' in body


def test_cancel_and_resume_preserve_checkpoint(tmp_path):
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/runs",
            json=payload(require_execution_approval=True),
        )
        run_id = created.json()["id"]
        waiting = wait_for_status(client, run_id, "waiting_approval")
        calls_before = waiting["agent_calls"]
        assert waiting["status"] == "waiting_approval"

        cancelled = client.post(f"/api/runs/{run_id}/cancel").json()
        assert cancelled["status"] == "cancelled"
        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 202
        waiting_again = wait_for_status(client, run_id, "waiting_approval")
        assert waiting_again["status"] == "waiting_approval"
        assert waiting_again["agent_calls"] == calls_before
        assert waiting_again["resume_count"] == 1


def test_quality_resume_prefix_keeps_completed_review_checkpoint(tmp_path):
    store = RunStore(tmp_path / "data")
    request = DemoRequest.model_validate(payload())
    run = DemoRun(
        id="abc123def456",
        request=request,
        status="failed",
        quality_gate="failed",
        revision_count=3,
        checkpoint="resume:agent:reviewer:iteration:3",
        outputs={
            "artifact_validation": {"status": "failed"},
            "artifact_validation_iteration_3": {"status": "failed"},
            "reviewer": {"decision": "revise"},
            "reviewer_iteration_3": {"decision": "revise"},
            "qa": {"decision": "revise"},
            "qa_iteration_3": {"decision": "revise"},
        },
    )
    store.create(run)
    manager = RunManager(store, None)  # type: ignore[arg-type]
    manager.schedule = lambda _run_id: None

    resumed = manager.resume(run)

    assert resumed.outputs["artifact_validation_iteration_3"]["status"] == "failed"
    assert resumed.outputs["reviewer_iteration_3"]["decision"] == "revise"
