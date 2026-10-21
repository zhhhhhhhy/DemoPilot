"""Regression authorization excludes all still-unseen cases and old outputs."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_sales_benchmark_pilot as pilot
import sales_observed_rerun as rerun


def fixture():
    ids = [f"observed-{i}" for i in range(15)]
    original = dict(batches=[dict(ids=ids[:5]), dict(ids=ids[5:]), dict(ids=["unseen"])], budget=dict(rerun.BUDGET))
    plan = dict(schema_version="observed-final15-regression-v1", ids=ids, budget=dict(rerun.BUDGET), original_delivered=13, remaining_unexecuted=85)
    split = dict(development=["dev"], validation=["validation"], heldout=[*ids, "unseen"])
    return plan, original, split


@pytest.mark.parametrize("defect", [None, "replace-with-unseen", "duplicate", "skip", "reorder", "model", "timeout", "call-cap", "history"])
def test_only_original_complete15_with_same_model_budget_and_history(defect):
    plan, original, split = fixture()
    if defect == "replace-with-unseen":
        plan["ids"][-1] = "unseen"
    elif defect == "duplicate":
        plan["ids"][-1] = plan["ids"][0]
    elif defect == "skip":
        plan["ids"].pop()
    elif defect == "reorder":
        plan["ids"].reverse()
    elif defect == "model":
        plan["budget"]["model"] = "another-model"
    elif defect == "timeout":
        plan["budget"]["cli_timeout_seconds"] = 900
    elif defect == "call-cap":
        plan["budget"]["intake_call_cap"] = 4
    elif defect == "history":
        plan["original_delivered"] = 15
    if defect is None:
        rerun.validate_selection(plan, original, split, "gpt-6.1-sol")
    else:
        with pytest.raises(ValueError):
            rerun.validate_selection(plan, original, split, "gpt-6.1-sol")


def test_no_implicit_rerun_authorization(tmp_path):
    with pytest.raises(ValueError, match="explicit exact"):
        rerun.unlock(None, "gpt-6.1-sol", tmp_path)


def test_rerun_keeps_heldout_split_but_not_original_campaign(tmp_path, monkeypatch):
    dataset = tmp_path / "data"
    dataset.mkdir()
    dev = [f"dev{i}" for i in range(20)]
    (dataset / "split.json").write_text(json.dumps(dict(development=dev, validation=[], heldout=["observed"])))
    (dataset / "pilot-20.json").write_text(json.dumps(dict(case_ids=dev)))
    monkeypatch.setattr(pilot, "DATASET", dataset)
    monkeypatch.setattr(pilot, "validate", lambda: dict(status="passed"))
    monkeypatch.setattr(pilot, "sha", lambda _p: "fixed")
    monkeypatch.setattr(pilot, "code_manifest", lambda: {"code": "fixed"})
    monkeypatch.setattr(rerun, "unlock", lambda *_a: (["observed"], dict(plan_sha256="fixed")))
    output = tmp_path / "out"
    output.mkdir()
    context = pilot.freeze(output, SimpleNamespace(cohort="observed15-rerun", model="gpt-6.1-sol", rerun_plan=rerun.PLAN))
    assert json.loads((output / "context.json").read_text("utf-8")) == context
    assert context["execution_split"] == "heldout" and context["pilot_ids"] == ["observed"]
    assert context["final_campaign"] is None and context["observed_rerun"]["plan_sha256"] == "fixed"
    with pytest.raises(RuntimeError, match="fresh cohort"):
        pilot.freeze(output, SimpleNamespace())
