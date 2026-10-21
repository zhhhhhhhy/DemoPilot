import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
import sales_runtime_campaign as campaign


def test_runtime_campaign_requires_explicit_plan(tmp_path):
    with pytest.raises(ValueError,match="explicit separate"):
        campaign.unlock(None,"gpt-6.1-sol",tmp_path)


def test_runtime_development_strata_are_original_development_only():
    ids=campaign.development_ids()
    split=campaign.read(campaign.DATASET/"split.json")
    assert len(ids)==len(set(ids))==2 and set(ids).issubset(split['development'])
    assert not set(ids)&set(split['heldout'])


def test_partial_development_or_wrong_source_cannot_unlock15(tmp_path,monkeypatch):
    monkeypatch.setattr(campaign,"development_ids",lambda:["dev-a","dev-b"])
    (tmp_path/"context.json").write_text(json.dumps(dict(pilot_ids=["dev-a"],execution_split='development')))
    (tmp_path/"results.json").write_text(json.dumps(dict(rows=[])))
    with pytest.raises(ValueError,match="both fixed"):
        campaign.qualified_development(tmp_path/"results.json","gpt-6.1-sol")


def test_runtime_injection_cannot_enter_scored15(tmp_path,monkeypatch):
    from types import SimpleNamespace

    import run_sales_benchmark_pilot as pilot
    monkeypatch.setattr(pilot,"validate",lambda:{})
    with pytest.raises(ValueError,match="only on development"):
        pilot.freeze(tmp_path,SimpleNamespace(cohort='runtime-repair15',runtime_resume_control=True))
    assert not (tmp_path/'context.json').exists()
