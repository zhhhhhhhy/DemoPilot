"""The added control changes information only, not Core instructions or gold."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_quotation_intent_ab as original
from run_quotation_full_rules import make_full_rules_request, supplied_facts


def test_all_full_rule_requests_change_only_business_information():
    for case in original.all_cases():
        before = original.make_request(case, "direct").model_dump(mode="json")
        after = make_full_rules_request(case).model_dump(mode="json")
        assert {key for key in before if before[key] != after[key]} == {"evaluation_intent"}
        assert after["evaluation_intent"] == case["raw_sales_brief"] + "\n销售已回答：" + "\n".join(supplied_facts(case))
        assert after["evaluation_goal"] is None
        assert after["must_haves"] == after["acceptance_criteria"] == after["evaluation_method"] == []
        assert after["evaluation_intent_profile"] == "raw-sales"
