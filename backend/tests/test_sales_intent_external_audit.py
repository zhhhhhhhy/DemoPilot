"""Missing/unpublished cases cannot disappear from experiment denominators."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from audit_sales_intent_paired_results import CASE_IDS, summarize_audit


def test_fixed_denominator_retains_missing_and_failed_cases():
    rows = [
        {"arm": "raw-sales", "case_id": CASE_IDS[0], "fixture_coverage_status": "passed", "business_status": "passed"},
        {"arm": "raw-sales", "case_id": CASE_IDS[1], "fixture_coverage_status": "failed", "business_status": "failed", "published_defect": True},
    ]
    metrics = summarize_audit(rows)
    assert metrics["raw-sales"]["business_pass_rate"] == "1/3"
    assert metrics["raw-sales"]["missing_cases"] == [CASE_IDS[2]]
    assert metrics["raw-sales"]["published_defect_cases"] == [CASE_IDS[1]]
    assert metrics["intent-agent"]["business_pass_rate"] == "0/3"
