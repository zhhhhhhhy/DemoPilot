from __future__ import annotations

import time

from fastapi.testclient import TestClient

from demopilot.config import Settings
from demopilot.evaluation_cases import builtin_evaluation_cases
from demopilot.evaluator import evaluate_demo_run
from demopilot.main import create_app
from demopilot.models import DemoRequest, DemoRun, RunStatus


def wait_for_evaluation(client: TestClient, evaluation_id: str, timeout: float = 90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.get(f"/api/evaluations/{evaluation_id}").json()
        if last["status"] in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"evaluation did not finish; last={last}")


def evaluation_payload(**overrides):
    payload = {
        "provider": "mock",
        "case_ids": ["ops-01"],
        "case_limit": 1,
        "concurrency": 1,
        "version_label": "test-baseline",
        "baseline_id": None,
        "thresholds": {
            "min_success_rate": 0.9,
            "min_average_score": 80,
            "min_browser_pass_rate": 0.9,
            "min_feature_coverage_rate": 0.95,
            "max_average_agent_calls": 12,
        },
    }
    payload.update(overrides)
    return payload


def test_builtin_suite_has_thirty_unique_cross_industry_cases():
    cases = builtin_evaluation_cases()
    assert len(cases) == 30
    assert len({case.id for case in cases}) == 30
    assert len({case.industry for case in cases}) >= 25
    assert {case.difficulty for case in cases} == {"basic", "standard", "edge"}
    assert sum(case.complexity == "simple" for case in cases) == 11
    assert sum(case.complexity == "complex" for case in cases) == 19
    assert all(
        case.complexity == ("complex" if case.difficulty == "edge" else "simple")
        for case in cases
    )
    expanded = [case for case in cases if "expanded" in case.tags]
    assert len(expanded) == 10
    assert all(len(case.must_haves) == 3 for case in expanded)
    assert all(case.difficulty == "edge" for case in expanded)


def test_real_provider_budget_is_hard_limited(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as client:
        response = client.post(
            "/api/evaluations",
            json=evaluation_payload(
                provider="deepseek",
                case_ids=[],
                case_limit=4,
            ),
        )
        assert response.status_code == 422
        assert "最多允许 3 个用例" in response.text


def test_evaluation_score_reflects_reviewer_quality_and_revision_cost():
    case = builtin_evaluation_cases()[0]
    run = DemoRun(
        id="scored-run",
        request=DemoRequest(
            client_name="评分客户",
            project_name=case.name,
            industry=case.industry,
            scenario=case.scenario,
            audience=case.audience,
            must_haves=case.must_haves,
            provider="deepseek",
            require_execution_approval=False,
        ),
        status=RunStatus.COMPLETED,
        progress=100,
        agent_calls=10,
        revision_count=1,
        quality_gate="passed",
    )
    run.outputs = {
        "build_provenance": {"source_mode": "agent_generated_files"},
        "artifact_validation": {
            "status": "passed",
            "issues": [],
            "feature_coverage": {
                "required": case.must_haves,
                "rendered": case.must_haves,
                "missing": [],
            },
            "browser_e2e": {"status": "passed", "issues": []},
        },
        "reviewer": {"overall_score": 97, "issues": []},
    }

    result = evaluate_demo_run(case, run)

    assert result.passed is True
    assert result.score == 94.75


def test_mock_evaluation_runs_full_evidence_loop_and_report(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as client:
        cases = client.get("/api/evaluation-cases")
        assert cases.status_code == 200
        assert len(cases.json()) == 30

        created = client.post("/api/evaluations", json=evaluation_payload())
        assert created.status_code == 202
        evaluation_id = created.json()["id"]
        completed = wait_for_evaluation(client, evaluation_id)

        assert completed["status"] == "completed"
        assert completed["verdict"] == "passed"
        assert completed["metrics"]["success_rate"] == 1
        assert completed["metrics"]["browser_pass_rate"] == 1
        assert completed["metrics"]["feature_coverage_rate"] == 1
        assert completed["metrics"]["average_score"] == 98
        assert completed["metrics"]["average_agent_calls"] == 9
        assert completed["metrics"]["complexity_breakdown"]["simple"]["passed_cases"] == 1
        assert all(gate["passed"] for gate in completed["gates"])
        result = completed["results"][0]
        assert result["passed"] is True
        assert result["source_mode"] == "controlled_template_fallback"
        assert result["browser_status"] == "passed"
        assert result["complexity"] == "simple"
        assert result["run_id"]

        run = client.get(f"/api/runs/{result['run_id']}").json()
        assert run["outputs"]["evaluation_trace"]["evaluation_id"] == evaluation_id
        assert run["outputs"]["evaluation_trace"]["builder_preflight_enabled"] is True
        assert len(run["outputs"]["evaluation_trace"]["input_sha256"]) == 64

        report = client.get(f"/api/evaluations/{evaluation_id}/report")
        assert report.status_code == 200
        assert "DemoPilot 自动评测报告" in report.text
        assert result["run_id"] in report.text

        with client.stream("GET", f"/api/evaluations/{evaluation_id}/events") as stream:
            body = "".join(stream.iter_text())
        assert "event: evaluation" in body
        assert '"status":"completed"' in body


def test_evaluation_can_disable_preflight_only_for_control_group(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as client:
        created = client.post(
            "/api/evaluations",
            json=evaluation_payload(builder_preflight_enabled=False),
        )
        completed = wait_for_evaluation(client, created.json()["id"])
        run_id = completed["results"][0]["run_id"]
        run = client.get(f"/api/runs/{run_id}").json()

        assert run["outputs"]["evaluation_trace"]["builder_preflight_enabled"] is False
        assert run["outputs"]["builder_preflight"]["status"] == "disabled"
        assert run["outputs"]["builder_preflight"]["evaluation_only"] is True


def test_evaluation_uses_latest_same_provider_baseline(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as client:
        first_id = client.post("/api/evaluations", json=evaluation_payload()).json()["id"]
        wait_for_evaluation(client, first_id)
        different_complexity_id = client.post(
            "/api/evaluations",
            json=evaluation_payload(
                complexity="simple",
                version_label="different-complexity",
            ),
        ).json()["id"]
        wait_for_evaluation(client, different_complexity_id)
        second = client.post(
            "/api/evaluations",
            json=evaluation_payload(version_label="test-candidate"),
        ).json()
        completed = wait_for_evaluation(client, second["id"])
        assert completed["comparison"]["baseline_id"] == first_id
        assert completed["comparison"]["success_rate_delta"] == 0
        assert completed["comparison"]["average_score_delta"] == 0


def test_evaluation_can_select_cases_by_complexity(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as client:
        created = client.post(
            "/api/evaluations",
            json=evaluation_payload(case_ids=[], case_limit=3, complexity="complex"),
        )
        assert created.status_code == 202
        payload = created.json()
        assert payload["request"]["complexity"] == "complex"
        assert len(payload["case_ids"]) == 3
        assert all(result["complexity"] == "complex" for result in payload["results"])


def test_explicit_case_ids_must_match_selected_complexity(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as client:
        response = client.post(
            "/api/evaluations",
            json=evaluation_payload(complexity="complex"),
        )
        assert response.status_code == 400
        assert "do not match complexity=complex" in response.text
