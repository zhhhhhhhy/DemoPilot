"""Missing-plan recovery must preserve sealed bytes and reject drift."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_sales_benchmark_private import prepare  # noqa: E402


def fixture(tmp_path):
    dataset = tmp_path / "evaluation_sets/sales-benchmark-v3"
    dataset.mkdir(parents=True)
    # Compile no profiles: sufficient to verify exact recovery/ownership, not
    # another test mirroring the full pricing implementation.
    contract = dict(id="sales-v3-001", version=1, profiles={})
    data = json.dumps(contract).encode()
    public = tmp_path / "testdata/sales-v3-001/contract.json"
    public.parent.mkdir(parents=True)
    public.write_bytes(data)
    expected = (
        json.dumps(
            dict(app_id="sales-v3-001", version=1, private=True, journeys=[]),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode()
    (dataset / "cases.json").write_text(json.dumps(dict(cases=[dict(id="sales-v3-001")])))
    (dataset / "manifest.json").write_text(
        json.dumps(
            dict(
                files={
                    "testdata/sales-v3-001/contract.json": hashlib.sha256(data).hexdigest(),
                    "evaluation_sets/sales-benchmark-v3/private/sales-v3-001.json": hashlib.sha256(
                        expected
                    ).hexdigest(),
                }
            )
        )
    )
    return dataset, public, expected


def test_missing_plan_recovered_once_with_exact_hash(tmp_path):
    dataset, public, expected = fixture(tmp_path)
    before = public.read_bytes()
    assert prepare(tmp_path)["created"] == 1
    assert (dataset / "private/sales-v3-001.json").read_bytes() == expected
    assert prepare(tmp_path)["created"] == 0
    assert public.read_bytes() == before


def test_drifted_existing_plan_is_never_replaced(tmp_path):
    dataset, _, _ = fixture(tmp_path)
    private = dataset / "private/sales-v3-001.json"
    private.parent.mkdir()
    private.write_bytes(b"bad")
    with pytest.raises(ValueError, match="will not overwrite"):
        prepare(tmp_path)
    assert private.read_bytes() == b"bad"


def test_original_windows_newline_hash_recovered_on_any_host(tmp_path):
    dataset, _, expected = fixture(tmp_path)
    windows_expected = expected.replace(b"\n", b"\r\n")
    manifest = json.loads((dataset / "manifest.json").read_text())
    manifest["files"]["evaluation_sets/sales-benchmark-v3/private/sales-v3-001.json"] = (
        hashlib.sha256(windows_expected).hexdigest()
    )
    (dataset / "manifest.json").write_text(json.dumps(manifest))
    assert prepare(tmp_path)["created"] == 1
    assert (dataset / "private/sales-v3-001.json").read_bytes() == windows_expected
