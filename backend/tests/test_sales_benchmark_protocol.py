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


def test_followup_repeats_original_pricing_without_accepting_proposed_change():
    case = dict(
        seller_answers=[
            dict(topic="pricing", aliases=["税"], answer="目录已含6%税，含税总价保持不变。"),
            dict(topic="shipping", aliases=["运费"], answer="普通配送12元。"),
        ]
    )
    question = ["是否确认改成8%税率？"]
    answer = pilot.answers_for(question, case, {"pricing"})
    assert [a["topic"] for a in answer] == ["pricing_clarification"]
    assert "目录已含6%税，含税总价保持不变。" in answer[0]["answer"]
    assert "8%" not in answer[0]["answer"] and "12元" not in answer[0]["answer"]
    assert pilot.answers_for(question, case, {"pricing", "pricing_clarification"}) == []


def test_validation40_does_not_launch_without_passed191(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    dev = [f"dev{i}" for i in range(20)]
    validation = [f"validation{i}" for i in range(40)]
    (dataset / "split.json").write_text(
        json.dumps(dict(development=dev, validation=validation, heldout=["final"]))
    )
    (dataset / "pilot-20.json").write_text(json.dumps(dict(case_ids=dev)))
    monkeypatch.setattr(pilot, "DATASET", dataset)
    monkeypatch.setattr(pilot, "validate", lambda: dict(status="passed"))
    with pytest.raises(ValueError, match="passed191"):
        pilot.freeze(tmp_path / "output", SimpleNamespace(model="unused", cohort="validation"))
    assert not (tmp_path / "output/context.json").exists()


@pytest.mark.parametrize(
    "defect", [None, "failed", "stale_source", "missing_asset", "wrong_case", "incomplete"]
)
def test_validation40_gate_requires_complete_current_source191(tmp_path, monkeypatch, defect):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_text("{}")
    evidence = tmp_path / "regression/results.json"
    evidence.parent.mkdir()
    code = {"runtime.py": "frozen"}
    context = dict(
        pilot_ids=["sales-v3-191"],
        targeted_regression=True,
        execution_split="development",
        model="frozen-model",
        dataset_manifest_sha256=pilot.sha(dataset / "manifest.json"),
        code_sha256=code,
    )
    row = dict(
        case_id="sales-v3-191",
        delivery_pass=True,
        confirmation_semantics_match=True,
        status="published",
        final_functional_pass=True,
        exact_served_assets=["index.html", "app.js", "styles.css"],
        independent_check=dict(
            status="passed", planned=7, executed=7, passed=7, source_unchanged=True
        ),
        cost=dict(core_calls=1),
    )
    if defect == "failed":
        row["delivery_pass"] = False
    elif defect == "stale_source":
        context["code_sha256"] = {"runtime.py": "old"}
    elif defect == "missing_asset":
        row["exact_served_assets"].pop()
    elif defect == "wrong_case":
        row["case_id"] = "sales-v3-001"
    elif defect == "incomplete":
        row["independent_check"]["executed"] = 6
    (evidence.parent / "context.json").write_text(json.dumps(context))
    evidence.write_text(json.dumps(dict(rows=[row])))
    monkeypatch.setattr(pilot, "ROOT", tmp_path)
    monkeypatch.setattr(pilot, "DATASET", dataset)
    monkeypatch.setattr(pilot, "code_manifest", lambda: code)
    if defect:
        with pytest.raises(ValueError, match="passed191"):
            pilot.validation_unlock(evidence, "frozen-model")
    else:
        assert pilot.validation_unlock(evidence, "frozen-model")["source_verified"]
