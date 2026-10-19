"""Small protocol checks, separate from real model/browser acceptance."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_sales_benchmark_pilot as pilot  # noqa: E402


def test_scripted_seller_releases_only_asked_unreleased_topics():
    case = dict(
        seller_answers=[
            dict(topic="catalogue", aliases=["单价"], answer="A=120"),
            dict(topic="pricing", aliases=["优惠"], answer="满3优惠10%"),
            dict(topic="shipping", aliases=["运费"], answer="普通20"),
        ]
    )
    assert [a["topic"] for a in pilot.answers_for(["普通运费是多少？"], case, set())] == [
        "shipping"
    ]
    assert pilot.answers_for(["单价是多少？"], case, {"catalogue"}) == []
    assert pilot.answers_for(["喜欢什么颜色？"], case, set()) == []


def test_semantic_confirmation_does_not_reject_decimal_or_catalogue_order():
    left = dict(
        title="old", catalogue=[dict(id="B", unit_price="100.00"), dict(id="A", unit_price="20")]
    )
    right = dict(
        title="new", catalogue=[dict(id="A", unit_price="20.00"), dict(id="B", unit_price="100")]
    )
    assert pilot.semantics(left) == pilot.semantics(right)
    right["catalogue"][0]["unit_price"] = "20.01"
    assert pilot.semantics(left) != pilot.semantics(right)


def test_freeze_refuses_heldout_in_pilot_before_any_model_launch(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "split.json").write_text(json.dumps(dict(development=["dev"], heldout=["final"])))
    (dataset / "pilot-20.json").write_text(json.dumps(dict(case_ids=["final"] * 20)))
    monkeypatch.setattr(pilot, "DATASET", dataset)
    monkeypatch.setattr(pilot, "validate", lambda: dict(status="passed"))
    with pytest.raises(AssertionError):
        pilot.freeze(tmp_path / "output", SimpleNamespace(model="unused"))
    assert not (tmp_path / "output/context.json").exists()


def test_existing_shared_workflow_can_answer_followup_actor_question():
    case = dict(
        expected_plan=dict(workflow="expiry"),
        seller_answers=[dict(topic="workflow", aliases=["审批"], answer="有效期内客户确认")],
    )
    answer = pilot.answers_for(["由谁审批？"], case, {"workflow"})
    assert answer[0]["topic"] == "workflow_common"
    assert "经理审批" in answer[0]["answer"]
    assert pilot.answers_for(["由谁审批？"], case, {"workflow", "workflow_common"}) == []


def test_windows_transcript_paths_classify_cost_without_losing_calls(tmp_path):
    event = json.dumps(
        dict(
            type="turn.completed",
            usage=dict(input_tokens=100, cached_input_tokens=40, output_tokens=10),
        )
    )
    for relative in (
        "intent/turn-1/stdout.jsonl",
        "revision-1/evidence/v1/iteration-0/cli/stdout.jsonl",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(event + "\n")
    cost = pilot.trace_cost(tmp_path)
    assert (cost["cli_process_calls"], cost["intake_calls"], cost["core_calls"]) == (2, 1, 1)
    assert cost["reported_root_tokens"] == dict(
        input_tokens=200, cached_input_tokens=80, output_tokens=20
    )


def test_regression_subset_cannot_include_a_final_case(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    ids = [f"dev{i}" for i in range(20)]
    (dataset / "split.json").write_text(json.dumps(dict(development=ids, heldout=["final"])))
    (dataset / "pilot-20.json").write_text(json.dumps(dict(case_ids=ids)))
    monkeypatch.setattr(pilot, "DATASET", dataset)
    monkeypatch.setattr(pilot, "validate", lambda: dict(status="passed"))
    with pytest.raises(ValueError, match="original20"):
        pilot.freeze(tmp_path / "output", SimpleNamespace(model="unused", regression_ids=["final"]))
