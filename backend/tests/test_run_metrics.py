import json

from fastapi.testclient import TestClient

from demopilot.config import Settings
from demopilot.main import create_app
from demopilot.models import DemoRequest, DemoRun, RunStatus
from demopilot.run_metrics import run_metrics


def test_metrics_sum_each_core_log_once_and_preserve_unknown_usage(tmp_path):
    run = DemoRun(id="012345abcdef", request=DemoRequest(
        client_name="Metrics test", project_name="Demo", industry="Sales",
        scenario="Show a local sales quote", audience="Sales", provider="codex_cli",
    ), status=RunStatus.FAILED, agent_calls=2)
    root = tmp_path / run.id
    builder = root / "artifacts/evidence/core/iteration-0"
    child = builder / "acceptance-child"
    child.mkdir(parents=True)
    (builder / "stdout.jsonl").write_text(json.dumps({
        "type": "turn.completed", "usage": {"input_tokens": 120, "cached_input_tokens": 50, "output_tokens": 20},
    }) + "\npartial-json", encoding="utf-8")
    (child / "stdout.jsonl").write_text('{"type":"turn.started"}\n', encoding="utf-8")
    (child / "stderr.log").write_text("tls handshake eof", encoding="utf-8")
    metrics = run_metrics(run, root)
    assert metrics["observed_cli_session_count"] == 2
    assert metrics["sessions_with_usage"] == 1
    assert metrics["observed_usage"] == {"input_tokens": 120, "cached_input_tokens": 50, "output_tokens": 20}
    assert metrics["usage_complete"] is False
    assert metrics["observed_failure_signals"] == ["transport"]
    assert run_metrics(run, tmp_path / "missing")["observed_usage"] is None


def test_readonly_metrics_endpoint_and_missing_run(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    run = DemoRun(id="012345abcdef", request=DemoRequest(
        client_name="Metrics test", project_name="Demo", industry="Sales",
        scenario="Show a local sales quote", audience="Sales", provider="codex_cli",
    ), status=RunStatus.CANCELLED)
    app.state.store.create(run)
    original = (tmp_path / "runs" / run.id / "run.json").read_bytes()
    with TestClient(app) as client:
        response = client.get(f"/api/runs/{run.id}/metrics")
        assert response.status_code == 200
        assert response.json()["terminal"] is True
        assert response.json()["observed_usage"] is None
        assert client.get("/api/runs/ffffffffffff/metrics").status_code == 404
    assert (tmp_path / "runs" / run.id / "run.json").read_bytes() == original
