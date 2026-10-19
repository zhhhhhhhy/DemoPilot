"""Protocol controls only; real network/model/browser evidence stays separate."""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from demopilot.providers.codex_cli import _cli_failure_detail

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_sales_benchmark_pilot as pilot


def test_workspace_failure_is_not_hidden_by_analytics_warning():
    stdout = b'{"type":"error","message":"reconnecting"}\n{"type":"turn.failed","error":{"message":"workspace routing discovery failed"}}\n'
    assert _cli_failure_detail(stdout, b"WARN analytics events request failed") == "workspace routing discovery failed"
    assert _cli_failure_detail(b"not-json", b"first\nTLS handshake eof") == "TLS handshake eof"


@pytest.mark.parametrize("defect", [None, "model", "business_source", "stale_readiness", "incomplete_readiness", "expired", "missing_browser"])
def test_recovery_keeps_original_failed_subset_budget_and_current_readiness(tmp_path, monkeypatch, defect):
    baseline = tmp_path / "original"
    baseline.mkdir()
    evidence = baseline / "results.json"
    ids = [f"case{i}" for i in range(40)]
    evidence.write_text(json.dumps(dict(rows=[dict(case_id=i, delivery_pass=n < 23) for n, i in enumerate(ids)])))
    code = {"business.py": "same", "scripts/run_sales_benchmark_pilot.py": "old"}
    context = dict(model="same-model", reasoning_effort="medium", cli_timeout_seconds=300,
        core_call_cap=3, intake_call_cap=3, max_parallel=2, case_deadline_seconds=2100,
        dataset_manifest_sha256="dataset", pilot_ids=ids, code_sha256=code)
    (baseline / "context.json").write_text(json.dumps(context))
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "split.json").write_text(json.dumps(dict(validation=ids, heldout=["untouched"])))
    current = {**code, "scripts/run_sales_benchmark_pilot.py": "new"}
    ready_code = dict(current)
    if defect == "business_source":
        current["business.py"] = "changed"
    if defect == "stale_readiness":
        ready_code["scripts/run_sales_benchmark_pilot.py"] = "old"
    ready = tmp_path / "ready.json"
    payload = dict(status="passed", model="same-model", reasoning_effort="medium", cli_timeout_seconds=300,
        python_executable=str((tmp_path / "backend/.venv/Scripts/python.exe").resolve()), browser_preflight=dict(passed=True),
        code_sha256=ready_code, created_at=datetime.now(UTC).isoformat(),
        rows=[dict(mode=m, passed=True, returncode=0) for m in ("read", "write")],
        trace_sha256={f"{m}/{f}": "trace" for m in ("read", "write") for f in ("stdout.jsonl", "stderr.log")})
    if defect == "incomplete_readiness":
        payload["rows"].pop()
    if defect == "expired":
        payload["created_at"] = "2020-01-01T00:00:00+00:00"
    if defect == "missing_browser":
        payload["browser_preflight"]["passed"] = False
    ready.write_text(json.dumps(payload))
    def sha(path):
        if path == evidence:
            return "2ea694d11c1082ee1b524e108f6989ebe6433f6cfa05cdbda1db9003c2ac6f82"
        if path == baseline / "context.json":
            return "f7404775bb14a52633e5a7b956b1b08ae014afd2bd97314b9087824028f2ec2e"
        return "dataset" if path.name == "manifest.json" else "trace"
    monkeypatch.setattr(pilot, "ROOT", tmp_path)
    monkeypatch.setattr(pilot, "sys", SimpleNamespace(executable=str((tmp_path / "backend/.venv/Scripts/python.exe").resolve())))
    monkeypatch.setattr(pilot, "DATASET", dataset)
    monkeypatch.setattr(pilot, "sha", sha)
    monkeypatch.setattr(pilot, "code_manifest", lambda: current)
    if defect:
        with pytest.raises(ValueError):
            pilot.transport_recovery_unlock(evidence, ready, "other-model" if defect == "model" else "same-model")
    else:
        failed, proof = pilot.transport_recovery_unlock(evidence, ready, "same-model")
        assert failed == ids[23:]
        assert proof["source_verified"]


def test_recovery_rejects_unsealed_baseline_before_readiness(tmp_path):
    fake = tmp_path / "results.json"
    fake.write_text('{"rows":[]}')
    with pytest.raises(ValueError, match="original23/40"):
        pilot.transport_recovery_unlock(fake, None, "gpt-6.1-sol")
