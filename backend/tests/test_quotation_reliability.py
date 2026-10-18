import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demopilot.quotation_api import create_app
from demopilot.quotation_browser import tree_hash
from demopilot.quotation_contract import QuoteModel
from demopilot.quotation_release import ReleaseRegistry, ReleaseRejected

ROOT = Path(__file__).resolve().parents[2]


def contract(i=1, version=1):
    return json.loads(
        (ROOT / f"testdata/qflow-{i:02d}/contract-v{version}.json").read_text("utf-8")
    )


def test_hand_calculated_money_and_approval_change():
    model = QuoteModel(contract(3, 2))
    model.apply(
        dict(
            action="calculate",
            values={
                "quantity": "12",
                "second_product": "A",
                "second_quantity": "3",
                "shipping": "express",
            },
        )
    )
    # 15*A100 at20% tier discount, plus50 freight =>1250, requires finance.
    assert model.snapshot()["total"] == "1250.00"
    model.apply(dict(action="submit"))
    model.apply(dict(role="manager", actor="manager1", action="approve"))
    assert model.current["state"] == "PendingFinance"
    model.apply(dict(role="finance", action="approve"))
    approved = deepcopy(model.snapshot())
    assert model.apply(dict(role="customer", action="calculate", values={"quantity": "2"})) is False
    assert model.snapshot() == approved
    model.apply(
        dict(
            role="seller",
            action="calculate",
            values={"quantity": "2", "second_quantity": "0", "shipping": "pickup"},
        )
    )
    assert model.current["state"] == "Draft" and model.snapshot()["approved_revision"] == "-1"
    assert model.snapshot()["total"] == "200.00"
    before = deepcopy(model.snapshot())
    model.apply(dict(action="calculate"))
    assert model.snapshot() == before


def test_rejection_separation_and_validity():
    model = QuoteModel(contract(4))
    model.apply(dict(action="submit"))
    model.apply(dict(role="manager", actor="manager1", action="approve"))
    assert model.current["state"] == "PendingManager"
    assert not model.apply(dict(action="approve"))
    model.apply(dict(actor="manager2", action="approve"))
    assert model.current["state"] == "Approved"
    model = QuoteModel(contract(5))
    model.apply(dict(action="submit"))
    assert not model.apply(dict(role="manager", reason=" ", action="reject"))
    model.apply(dict(reason="Fix quote", action="reject"))
    assert model.current["state"] == "Rejected"
    model = QuoteModel(contract(8))
    model.apply(dict(action="submit"))
    model.apply(dict(role="manager", action="approve"))
    assert not model.apply(dict(role="customer", today="2026-04-01", action="accept"))
    assert model.apply(dict(today="2026-03-31", action="accept"))
    model = QuoteModel(contract(9))
    model.apply(dict(action="submit"))
    model.apply(dict(role="manager", action="approve"))
    model.apply(dict(record="Q2", role="seller", action="calculate", values={"quantity": "3"}))
    model.apply(dict(action="reload"))
    assert model.record == "Q1" and model.current["state"] == "Approved"


def artifact(tmp_path):
    p = tmp_path / "app"
    p.mkdir()
    (p / "index.html").write_text("<h1>verified</h1>")
    return p


def passed_report(path):
    return dict(
        status="passed",
        source_sha256=tree_hash(path),
        source_unchanged=True,
        planned_journeys=1,
        executed_journeys=1,
        passed_journeys=1,
    )


def test_atomic_revision_idempotence_and_read_api(tmp_path):
    reg = ReleaseRegistry(tmp_path / "registry")
    source = artifact(tmp_path)
    reg.set_intent("quote", 1, dict(rules="v1"))
    job = reg.claim("quote", 1, "j1")
    check = reg.record_check("j1", job["token"], tree_hash(source), passed_report(source))
    first = reg.publish("j1", job["token"], check, source)
    assert reg.publish("j1", job["token"], check, source) == first
    client = TestClient(create_app(reg.root))
    assert client.get("/projects/quote/demo/index.html").text == "<h1>verified</h1>"
    assert "token" not in client.get("/api/projects").text
    reg.set_intent("quote", 2, dict(rules="v2"))
    assert reg.resolve("quote") is None
    assert client.get("/projects/quote/demo/index.html").status_code == 404
    with pytest.raises(ReleaseRejected, match="superseded"):
        reg.publish("j1", job["token"], check, source)
    assert len([e for e in reg.snapshot()["events"] if e["kind"] == "published"]) == 1


def test_fail_closed_and_concurrent_claim(tmp_path):
    reg = ReleaseRegistry(tmp_path / "registry")
    source = artifact(tmp_path)
    reg.set_intent("q", 1, dict(goal="v1"))

    def claim(i):
        try:
            return reg.claim("q", 1, f"job{i}")
        except ReleaseRejected:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(claim, range(8)))
    winners = [j for j in jobs if j]
    assert len(winners) == 1
    job = winners[0]
    bad = dict(passed_report(source), status="failed")
    failed = reg.record_check(job["id"], job["token"], tree_hash(source), bad)
    with pytest.raises(ReleaseRejected):
        reg.publish(job["id"], job["token"], failed, source)
    engineering = reg.record_check(
        job["id"],
        job["token"],
        tree_hash(source),
        passed_report(source),
        kind="engineering-control",
    )
    with pytest.raises(ReleaseRejected, match="Business acceptance"):
        reg.publish(job["id"], job["token"], engineering, source)
    check = reg.record_check(job["id"], job["token"], tree_hash(source), passed_report(source))
    (source / "index.html").write_text("tampered after check")
    with pytest.raises(ReleaseRejected):
        reg.publish(job["id"], job["token"], check, source)
    assert reg.resolve("q") is None


def test_immutable_release_tamper_detected_and_intent_rewrite_denied(tmp_path):
    reg = ReleaseRegistry(tmp_path / "registry")
    source = artifact(tmp_path)
    reg.set_intent("q", 1, dict(goal="v1"))
    job = reg.claim("q", 1, "j")
    check = reg.record_check("j", job["token"], tree_hash(source), passed_report(source))
    reg.publish("j", job["token"], check, source)
    path = Path(reg.resolve("q")["path"])
    (path / "index.html").write_text("changed")
    with pytest.raises(ReleaseRejected, match="tampered"):
        reg.resolve("q")
    with pytest.raises(ReleaseRejected):
        reg.set_intent("q", 1, dict(goal="different"))
    with pytest.raises(ReleaseRejected):
        ReleaseRegistry(reg.root, require_business=False)


def test_bundle_url_pins_accepted_bytes_across_new_revision(tmp_path):
    reg = ReleaseRegistry(tmp_path / "registry")
    source = artifact(tmp_path)
    (source / "app.js").write_text("const version=1")
    reg.set_intent("q", 1, {"goal": "v1"})
    job = reg.claim("q", 1, "j1")
    check = reg.record_check("j1", job["token"], tree_hash(source), passed_report(source))
    reg.publish("j1", job["token"], check, source)
    client = TestClient(create_app(reg.root))
    response = client.get("/projects/q/demo/index.html", follow_redirects=False)
    assert response.status_code == 307
    pinned_index = response.headers["location"]
    pinned_js = pinned_index.rsplit("/", 1)[0] + "/app.js"
    reg.set_intent("q", 2, {"goal": "v2"})
    assert client.get("/projects/q/demo/index.html").status_code == 404
    assert client.get(pinned_js).text == "const version=1"
    (source / "app.js").write_text("const version=2")
    job2 = reg.claim("q", 2, "j2")
    check2 = reg.record_check("j2", job2["token"], tree_hash(source), passed_report(source))
    reg.publish("j2", job2["token"], check2, source)
    assert client.get("/projects/q/demo/app.js").text == "const version=2"
    assert client.get(pinned_js).text == "const version=1"
