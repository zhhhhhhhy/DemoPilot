"""Small checks of measurement integrity, not mock generator success."""
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from audit_quotation_intent import compare_outputs, input_boundary_audit, numeric, read_outputs
from materialize_quotation_intent import definitions, payloads
from quotation_oracle import expected_quote, money
from run_quotation_intent_ab import make_request, matched_seller_answers


def test_exact_numeric_measurement_rejects_substrings_and_ambiguous_outputs():
    assert numeric("CNY 1,234.50") == Decimal("1234.50")
    with pytest.raises(ValueError):
        numeric("原价100，合计90")
    values = dict(subtotal=Decimal("100"), discount=Decimal("10"), tax=Decimal("0"),
                  total=Decimal("900"), free_quantity=Decimal("0"))
    expected = dict(subtotal="100", discount="10", tax="0", total="90", free_quantity=0)
    assert [v["field"] for v in compare_outputs(values, expected)] == ["total"]


def test_hand_calculated_development_boundary_and_compounding():
    specs = definitions()
    _, _, _, tiers = payloads(specs[0])
    # Five at 100 with a ten-percent adjustment is 450, not 500.
    assert expected_quote(tiers, tiers["vectors"][2]) == dict(
        subtotal="500.00", discount="50.00", tax="0.00", total="450.00", free_quantity=0)
    _, _, _, compounded = payloads(specs[3])
    assert expected_quote(compounded, compounded["vectors"][0])["total"] == "72.00"
    assert money("1.005") == Decimal("1.01")


def test_business_answers_require_a_relevant_question_and_are_not_repeated():
    case, _, script, _ = payloads(definitions()[0])
    assert matched_seller_answers(["页面用什么颜色？"], script, set()) == ([], [])
    released, matches = matched_seller_answers(["数量优惠的规则是什么？"], script, set())
    assert len(released) == len(matches) == 1
    assert matched_seller_answers(["优惠门槛是什么？"], script, {"thresholds"}) == ([], [])
    # Asking who the customer is must not unlock the pricing thresholds.
    released, _ = matched_seller_answers(["客户是谁？"], script, set())
    assert all(answer["topic"] != "thresholds" for answer in released)
    direct = make_request(case, "direct")
    assert "5到9" not in direct.model_dump_json()


def test_declared_split_and_full_manifest_have_no_business_policy_in_fixtures():
    definitions_list = definitions()
    assert len(definitions_list) == 10
    assert len({c["family"] for c in definitions_list}) == 10
    assert [c["id"] for c in definitions_list if c["split"] == "development"] == [
        "quotation-01", "quotation-02", "quotation-03", "quotation-04"]
    assert len([c for c in definitions_list if c["split"] == "heldout"]) == 6
    for definition in definitions_list:
        case, fixture, answers, private = payloads(definition)
        assert "rules" not in fixture and "rule_config" not in fixture
        assert definition["policy"] not in json.dumps(fixture, ensure_ascii=False)
        assert private["vectors"] and case["source_urls"]


def test_real_browser_measurement_rejects_wrong_or_hidden_result():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<div id="subtotal">100.00</div><div id="discount">10.00</div>'
                '<div id="tax">0.00</div><div id="total">CNY 90.00</div>'
                '<div id="free-quantity">0</div>')
            expected = dict(subtotal="100", discount="10", tax="0", total="90", free_quantity=0)
            _, values = read_outputs(page)
            assert compare_outputs(values, expected) == []
            page.locator("#total").evaluate("node => node.textContent = 'CNY 900.00'")
            _, values = read_outputs(page)
            assert compare_outputs(values, expected)[0]["field"] == "total"
            page.locator("#total").evaluate("node => node.style.display = 'none'")
            with pytest.raises(AssertionError, match="not visible"):
                read_outputs(page)
        finally:
            browser.close()


def test_boundary_audit_allows_current_workspace_but_rejects_private_reads(tmp_path):
    run_dir = tmp_path / "evaluation_sets" / "results" / "run"
    log = run_dir / "artifacts/evidence/core/iteration-0/stdout.jsonl"
    log.parent.mkdir(parents=True)
    row = dict(run_dir=str(run_dir), case_id="quotation-01", arm="direct")
    def event(command):
        return json.dumps(dict(type="item.completed", item=dict(type="command_execution", command=command)))
    log.write_text(event(f"python core_acceptance_cli.py --workspace {run_dir}/core-workspace"), encoding="utf-8")
    assert input_boundary_audit(row, tmp_path)["status"] == "passed"
    with log.open("a", encoding="utf-8") as handle:
        handle.write("\n" + event("Get-Content evaluation_sets/quotation-intent-v1/private/quotation-01.json"))
    assert input_boundary_audit(row, tmp_path)["status"] == "contaminated"
