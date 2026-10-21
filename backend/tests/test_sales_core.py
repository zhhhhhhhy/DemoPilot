"""Controlled wiring regressions; real CLI/browser acceptance is separate."""

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from demopilot.config import Settings
from demopilot.main import create_app
from demopilot.quotation_browser import tree_hash
from demopilot.quotation_contract import compile_acceptance
from demopilot.sales_contract import QuotePlan
from demopilot.sales_core import SalesCoreManager, final_object

ROOT = Path(__file__).resolve().parents[2]
ANSWER = "A120、B80、C200；A满3件优惠10%，满8件优惠20%；两位不同经理审批。"
PLAN = dict(
    title="数量优惠与经理会签", catalogue=[dict(id=k, name=k, unit_price=v) for k, v in (("A", "120"), ("B", "80"), ("C", "200"))],
    pricing_rule=dict(kind="quantity_tiers", product="A", tiers=[dict(minimum=3, percent="10"), dict(minimum=8, percent="20")]),
    workflow="dual_manager",
)


async def interviewer(_prompt, messages, _transcript):
    if sum(m["role"] == "user" for m in messages) == 1:
        return dict(status="needs_details", title="报价需求", clarifications=[dict(
            question="三款商品的单价、优惠档位和审批人员分别是什么？",
            field_ids=["catalogue", "pricing_rule", "workflow"], reason="missing",
        )], proposal=None, source_quotes=[])
    return dict(status="ready", title=PLAN["title"], questions=[], proposal=PLAN, source_quotes=["A120", "两位不同经理"])


class ControlledHarness:
    name = "controlled-unit-fixture"

    def __init__(self, *, wait=False):
        self.calls = 0
        self.wait = wait

    async def build(self, **kwargs):
        self.calls += 1
        if self.wait:
            await asyncio.sleep(60)
        app = kwargs["workspace"] / "card-web"
        app.mkdir(exist_ok=True)
        (app / "index.html").write_text(f"<html><h1>Controlled test round {self.calls}</h1></html>")
        (app / "app.js").write_text("const fixture=true;")
        (app / "styles.css").write_text("body{color:black}")
        return dict(returncode=0)


def setup(tmp_path, monkeypatch, *, failures=0, wait=False):
    harness = ControlledHarness(wait=wait)
    checks = []

    async def audit(app, _contract, _evidence, **_kwargs):
        checks.append(tree_hash(app))
        passed = len(checks) > failures
        return dict(status="passed" if passed else "failed", source_sha256=tree_hash(app), source_unchanged=True,
                    planned_journeys=6, executed_journeys=6, passed_journeys=6 if passed else 5,
                    issues=[] if passed else ["Controlled business rejection: incorrect total"])

    monkeypatch.setattr("demopilot.quotation_loop.audit_application", audit)
    settings = Settings(data_dir=tmp_path / "data")
    manager = SalesCoreManager(settings, harness=harness, interviewer=interviewer, project_root=ROOT)
    return manager, harness, checks, settings


def wait_status(client, identifier, statuses):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        value = client.get(f"/api/sales-core/sessions/{identifier}").json()
        if value["status"] in statuses:
            return value
        time.sleep(.02)
    raise AssertionError(f"Unexpected terminal wait: {value['status']}")


def ready(client):
    initial = client.post("/api/sales-core/sessions", json=dict(brief="做一个数量优惠报价演示", request_key="controlled-request-001")).json()
    identifier = initial["id"]
    wait_status(client, identifier, {"needs_details"})
    client.post(f"/api/sales-core/sessions/{identifier}/answers", json=dict(answer=ANSWER))
    return wait_status(client, identifier, {"ready"})


def test_confirmed_workflow_rejects_then_repairs_and_publishes_once(tmp_path, monkeypatch):
    manager, harness, checks, settings = setup(tmp_path, monkeypatch, failures=1)
    with TestClient(create_app(settings, sales_core=manager)) as client:
        session = ready(client)
        identifier = session["id"]
        assert harness.calls == 0 and session["demo_url"] is None
        assert client.post(f"/api/sales-core/sessions/{identifier}/confirm", json=dict(draft_hash="0" * 64)).status_code == 409
        payload = dict(draft_hash=session["draft_hash"])
        client.post(f"/api/sales-core/sessions/{identifier}/confirm", json=payload)
        client.post(f"/api/sales-core/sessions/{identifier}/confirm", json=payload)
        result = wait_status(client, identifier, {"published", "failed"})
        assert result["status"] == "published" and result["iteration"] == 2
        assert harness.calls == len(checks) == 2
        assert result["revision"] == 1 and len(result["versions"]) == 1
        assert any(e["kind"] == "checked" and e["status"] == "failed" for e in result["events"])
        response = client.get(result["demo_url"])
        assert response.status_code == 200 and "Controlled test round 2" in response.text
        assert "connect-src 'none'" in response.headers["content-security-policy"]
        assert client.get(result["demo_url"].replace("index.html", "%2e%2e/session.json")).status_code == 404


def test_budget_exhaustion_and_unconfirmed_intent_remain_hidden(tmp_path, monkeypatch):
    manager, harness, _checks, settings = setup(tmp_path, monkeypatch, failures=99)
    with TestClient(create_app(settings, sales_core=manager)) as client:
        initial = client.post("/api/sales-core/sessions", json=dict(brief="一个报价应用", request_key="controlled-request-002")).json()
        duplicate = client.post("/api/sales-core/sessions", json=dict(brief="一个报价应用", request_key="controlled-request-002")).json()
        assert duplicate["id"] == initial["id"]
        assert client.post(f"/api/sales-core/sessions/{initial['id']}/confirm", json=dict(draft_hash="0" * 64)).status_code == 409
        session = ready(client)
        client.post(f"/api/sales-core/sessions/{session['id']}/confirm", json=dict(draft_hash=session["draft_hash"]))
        result = wait_status(client, session["id"], {"failed"})
        assert harness.calls == 3 and result["demo_url"] is None
        assert manager.registry.resolve(session["id"]) is None


def test_cancel_and_restart_recovery_use_new_revision(tmp_path, monkeypatch):
    manager, harness, _checks, settings = setup(tmp_path, monkeypatch, wait=True)
    with TestClient(create_app(settings, sales_core=manager)) as client:
        session = ready(client)
        identifier = session["id"]
        client.post(f"/api/sales-core/sessions/{identifier}/confirm", json=dict(draft_hash=session["draft_hash"]))
        wait_status(client, identifier, {"building"})
        cancelled = client.post(f"/api/sales-core/sessions/{identifier}/cancel").json()
        assert cancelled["status"] == "cancelled" and cancelled["demo_url"] is None
        assert manager.registry.resolve(identifier) is None
        # Simulate persisted in-flight state from an abrupt old process exit.
        manager.store.change(identifier, lambda s: s.update(status="building"))
    recovered, new_harness, _checks, settings = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, sales_core=recovered)) as client:
        previous = client.get(f"/api/sales-core/sessions/{identifier}").json()
        assert previous["status"] == "interrupted" and previous["messages"]
        client.post(f"/api/sales-core/sessions/{identifier}/retry")
        result = wait_status(client, identifier, {"published", "failed"})
        assert result["status"] == "published" and result["revision"] == 2
        assert new_harness.calls == 1 and result["demo_url"]


def test_real_user_rule_boundaries_and_alternative_default_profile():
    plan = QuotePlan.model_validate(PLAN)
    contract = plan.contract("a" * 16)
    assert {v["quantity"] for v in contract["boundary_vectors"]["quantity_tiers"]} == {"2", "3", "4", "7", "8", "9"}
    assert len(compile_acceptance(contract)["journeys"]) == 6
    changed = dict(PLAN, pricing_rule=dict(kind="customer_scope", product="A", discounts=dict(vip="12")))
    assert len(compile_acceptance(QuotePlan.model_validate(changed).contract("b" * 16))["journeys"]) == 6
    with pytest.raises(ValidationError):
        QuotePlan.model_validate(dict(PLAN, workflow="threshold"))


def test_parse_retained_cli_final_message_not_sanitized_event_summary(tmp_path):
    path = tmp_path / "stdout.jsonl"
    path.write_text('{"type":"item.completed","item":{"type":"agent_message","text":"{\\\"ok\\\":true}"}}\n')
    assert final_object(dict(events=[dict(type="item.completed", item_type="agent_message")], transcript=dict(stdout=str(path)))) == {"ok": True}


def test_changed_capability_version_requires_reconfirmation(tmp_path, monkeypatch):
    manager, harness, _checks, settings = setup(tmp_path, monkeypatch)
    with TestClient(create_app(settings, sales_core=manager)) as client:
        session = ready(client)
        monkeypatch.setattr("demopilot.sales_core.capability_identity", lambda: dict(version="changed", sha256="0" * 64))
        response = client.post(f"/api/sales-core/sessions/{session['id']}/confirm", json=dict(draft_hash=session["draft_hash"]))
        assert response.status_code == 409
        assert harness.calls == 0 and manager.registry.resolve(session["id"]) is None


def test_cli_timeout_never_publishes_even_when_generated_app_checks_pass(tmp_path, monkeypatch):
    manager, harness, checks, settings = setup(tmp_path, monkeypatch)
    real_build = harness.build

    async def interrupted(**kwargs):
        await real_build(**kwargs)
        raise RuntimeError("Injected CLI process timed out without turn.completed")

    harness.build = interrupted
    with TestClient(create_app(settings, sales_core=manager)) as client:
        session = ready(client)
        client.post(f"/api/sales-core/sessions/{session['id']}/confirm", json=dict(draft_hash=session["draft_hash"]))
        result = wait_status(client, session["id"], {"failed"})
        assert harness.calls == len(checks) == 3
        assert result["demo_url"] is None and manager.registry.resolve(session["id"]) is None
