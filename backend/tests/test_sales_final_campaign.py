"""Final-cohort authorization, immutable selection and progressive stop gates."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import sales_final_campaign as final


def fixture():
    metadata = []
    for difficulty, count in (("simple", 6), ("medium", 8), ("hard", 6)):
        for family in range(count):
            for variant in range(5):
                metadata.append(dict(id=f"{difficulty}-{family}-{variant}", difficulty=difficulty,
                                     family=f"{difficulty}-{family}"))
    batches = [dict(index=i, ids=ids, output=f"batch-{i}")
               for i, ids in enumerate(final.schedule(metadata), 1)]
    plan = dict(schema_version="authorized-final100-staged-v1", batches=batches, budget=dict(final.BUDGET))
    split = dict(development=["dev"], validation=["validation"], heldout=[x["id"] for x in metadata])
    return plan, split


def test_schedule_first5_covers_difficulties_without_duplicate_or_missing_tasks():
    plan, split = fixture()
    final.validate_plan(plan, split, "gpt-6.1-sol")
    assert {identifier.split("-")[0] for identifier in plan["batches"][0]["ids"]} == {"simple", "medium", "hard"}
    assert len(plan["batches"]) == 11


@pytest.mark.parametrize("defect", ["duplicate", "foreign", "model", "budget", "size"])
def test_changed_final_selection_or_budget_is_rejected(defect):
    plan, split = fixture()
    if defect == "duplicate":
        plan["batches"][0]["ids"][1] = plan["batches"][0]["ids"][0]
    elif defect == "foreign":
        plan["batches"][0]["ids"][0] = "dev"
    elif defect == "model":
        plan["budget"]["model"] = "another-model"
    elif defect == "budget":
        plan["budget"]["core_call_cap"] = 4
    else:
        plan["batches"][0]["ids"].append(plan["batches"][1]["ids"].pop())
    with pytest.raises(ValueError):
        final.validate_plan(plan, split, "gpt-6.1-sol")


def test_incomplete_or_failed_batch_blocks_later_batch():
    result = dict(summary=dict(planned=2, terminal=2), rows=[
        dict(case_id=i, delivery_pass=True, final_functional_pass=True) for i in ("one", "two")])
    final.require_complete_pass(result, ["one", "two"])
    incomplete = copy.deepcopy(result)
    incomplete["rows"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        final.require_complete_pass(incomplete, ["one", "two"])
    failed = copy.deepcopy(result)
    failed["rows"][0]["delivery_pass"] = False
    with pytest.raises(ValueError, match="failed"):
        final.require_complete_pass(failed, ["one", "two"])
    contaminated = copy.deepcopy(result)
    contaminated["summary"]["observed_input_flags"] = 1
    with pytest.raises(ValueError, match="audit"):
        final.require_complete_pass(contaminated, ["one", "two"])


def test_heldout_has_no_implicit_authorization(tmp_path):
    with pytest.raises(ValueError, match="exact plan path"):
        final.unlock(None, 1, "gpt-6.1-sol", tmp_path)
