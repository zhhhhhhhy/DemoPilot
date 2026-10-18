import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from materialize_business_gates import build_cases


def test_versioned_gates_cover_all_fixture_combinations_and_selection():
    cases = build_cases()
    assert [len(case["contract"]["tests"]) for case in cases] == [9, 4, 11]
    for case in cases:
        controls = case["contract"]["controls"]
        for test in case["contract"]["tests"]:
            for step in test["steps"]:
                assert step["selector"] in controls
                assert set(step["assertions"]) <= set(controls)
    assert cases[1]["inputs"]["fixtures"]["task_list_scope"].startswith("global:")
    assert len(cases[2]["inputs"]["fixtures"]["suppliers"]) == 3
    assert "#supplier" in cases[2]["contract"]["controls"]
