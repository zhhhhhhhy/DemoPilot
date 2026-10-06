"""Materialize the authored evaluation inputs and acceptance contracts.

The v1 case file is kept as historical benchmark input.  This script creates a
run-time contract under the repository root so a Core Builder receives an
explicit, inspectable data location instead of an implicit prompt-only fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SET_ROOT = ROOT / "evaluation_sets" / "codex-cli-v1"
CASES_PATH = SET_ROOT / "cases.json"
MANIFEST_PATH = SET_ROOT / "invoice-manifest.json"
TESTDATA_ROOT = ROOT / "testdata"
SAFE_SELECTOR = re.compile(r"^[#.][A-Za-z][A-Za-z0-9_-]*$")
ALLOWED_ACTIONS = {"click", "fill", "select"}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_acceptance(case_id: str, case_root: Path, acceptance: dict[str, Any], assets: list[dict[str, Any]]) -> list[str]:
    """Audit that every authored case has an executable, local contract.

    This is intentionally a static contract audit. It proves that the
    acceptance data can be executed by the Core Acceptance Runner; the runner
    still performs the real Chromium check only after a Builder has produced
    card-web files.
    """

    issues: list[str] = []
    required = ("intent", "goal", "flow_steps", "expected_result", "evaluation_method", "tests", "policy")
    for field in required:
        value = acceptance.get(field)
        if not value:
            issues.append(f"missing acceptance field: {field}")
    tests = acceptance.get("tests")
    controls = acceptance.get("controls") if isinstance(acceptance.get("controls"), dict) else {}
    if not isinstance(tests, list) or not tests:
        issues.append("tests must be a non-empty list")
    else:
        for test_index, test in enumerate(tests):
            if not isinstance(test, dict) or not str(test.get("id", "")).strip():
                issues.append(f"test[{test_index}] has no id")
                continue
            steps = test.get("steps")
            if not isinstance(steps, list) or not steps:
                issues.append(f"test[{test_index}] has no executable steps")
                continue
            for step_index, step in enumerate(steps):
                if not isinstance(step, dict):
                    issues.append(f"test[{test_index}].step[{step_index}] is not an object")
                    continue
                action = str(step.get("action", ""))
                selector = str(step.get("selector", ""))
                if action not in ALLOWED_ACTIONS:
                    issues.append(f"test[{test_index}].step[{step_index}] has unsupported action {action!r}")
                if not SAFE_SELECTOR.fullmatch(selector):
                    issues.append(f"test[{test_index}].step[{step_index}] has unsafe selector {selector!r}")
                if selector not in controls:
                    issues.append(f"test[{test_index}].step[{step_index}] selector is not declared in controls: {selector}")
                assertions = step.get("assertions", {})
                if not isinstance(assertions, dict):
                    issues.append(f"test[{test_index}].step[{step_index}] assertions must be an object")
                    continue
                for target, expected in assertions.items():
                    target = str(target)
                    if not SAFE_SELECTOR.fullmatch(target):
                        issues.append(f"test[{test_index}].step[{step_index}] has unsafe assertion selector {target!r}")
                    if target not in controls:
                        issues.append(f"test[{test_index}].step[{step_index}] assertion is not declared in controls: {target}")
                    if not isinstance(expected, dict):
                        issues.append(f"test[{test_index}].step[{step_index}] assertion {target} must be an object")
                    elif not expected.get("contains") and not expected.get("excludes") and not expected.get("changed"):
                        issues.append(f"test[{test_index}].step[{step_index}] assertion {target} has no observable expectation")
    for asset in assets:
        relative = Path(str(asset.get("relative_path", "")))
        if not relative.parts or ".." in relative.parts:
            issues.append(f"asset path escapes case directory: {relative}")
            continue
        path = case_root / relative
        if not path.is_file():
            issues.append(f"missing fixture file: {relative.as_posix()}")
        elif _sha256(path) != asset.get("sha256"):
            issues.append(f"fixture hash mismatch: {relative.as_posix()}")
    return sorted(set(issues))


def load_inputs() -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    evaluation = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in evaluation["cases"]}
    fixtures = {item["id"]: item for item in manifest["fixtures"]}
    if len(cases) != 20 or Counter(item["difficulty"] for item in cases.values()) != Counter(simple=10, medium=5, hard=5):
        raise ValueError("cases.json must contain exactly simple=10, medium=5, hard=5")
    return evaluation, cases, fixtures


def materialize() -> dict[str, Any]:
    _evaluation, cases, fixtures = load_inputs()
    TESTDATA_ROOT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for case_id, case in cases.items():
        case_root = TESTDATA_ROOT / case_id
        assets: list[dict[str, Any]] = []
        for asset_id in case.get("assets", []):
            fixture = fixtures.get(asset_id)
            if not fixture:
                raise ValueError(f"{case_id}: unknown fixture {asset_id}")
            source = (ROOT / fixture["local_path"]).resolve()
            if not source.is_file() or _sha256(source) != fixture["sha256"]:
                raise ValueError(f"{case_id}: fixture hash check failed for {source}")
            relative = Path("assets") / "invoices" / source.name
            target = case_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            assets.append({
                "id": asset_id,
                "relative_path": relative.as_posix(),
                "sha256": fixture["sha256"],
                "source": fixture["source"],
            })

        contract = case.get("browser_contract") or {}
        acceptance = {
            "schema_version": "core-acceptance-v2",
            "case_id": case_id,
            "difficulty": case["difficulty"],
            "intent": case["intent"],
            "goal": case["goal"],
            "flow_steps": case["flow_steps"],
            "expected_result": case["acceptance_criteria"],
            "evaluation_method": case["evaluation_method"],
            "controls": contract.get("controls", {}),
            "tests": contract.get("tests", []),
            "policy": contract.get("policy", "Every journey starts from a fresh page; missing evidence fails."),
            "runner": {
                "command": "python scripts/core_acceptance_cli.py --workspace <run-workspace> --case-id " + case_id,
                "authoritative_runner": "DemoPilot Core Acceptance Runner",
                "publish_only_after": "all tests passed and the latest source hash matches the tested source",
            },
        }
        inputs = {
            "schema_version": "core-inputs-v2",
            "case_id": case_id,
            "industry": case["industry"],
            "audience": case["audience"],
            "scenario": case["scenario"],
            "fixtures": contract.get("fixture", {}),
            "assets": assets,
            "paths": {
                "acceptance": f"testdata/{case_id}/acceptance.json",
                "inputs": f"testdata/{case_id}/inputs.json",
                "asset_root": f"testdata/{case_id}/assets",
            },
        }
        _write_json(case_root / "inputs.json", inputs)
        _write_json(case_root / "acceptance.json", acceptance)
        _write_json(case_root / "manifest.json", {
            "case_id": case_id,
            "difficulty": case["difficulty"],
            "files": [
                {"path": "inputs.json", "sha256": _sha256(case_root / "inputs.json")},
                {"path": "acceptance.json", "sha256": _sha256(case_root / "acceptance.json")},
                *[
                    {"path": item["relative_path"], "sha256": item["sha256"]}
                    for item in assets
                ],
            ],
        })
        case_issues = _validate_acceptance(case_id, case_root, acceptance, assets)
        records.append({
            "case_id": case_id,
            "difficulty": case["difficulty"],
            "path": f"testdata/{case_id}",
            "acceptance_path": f"testdata/{case_id}/acceptance.json",
            "input_path": f"testdata/{case_id}/inputs.json",
            "asset_count": len(assets),
            "test_count": len(acceptance["tests"]),
            "status": "passed" if not case_issues else "failed",
            "issues": case_issues,
        })

    audit = {
        "schema_version": "core-evaluation-audit-v2",
        "source": "evaluation_sets/codex-cli-v1/cases.json",
        "case_count": len(records),
        "tier_counts": dict(Counter(item["difficulty"] for item in records)),
        "acceptance_definition": {
            "required_files": ["inputs.json", "acceptance.json", "manifest.json"],
            "required_acceptance_fields": ["intent", "goal", "flow_steps", "expected_result", "evaluation_method", "tests", "policy"],
            "test_rule": "Each test must have at least one safe selector/action step; every action and assertion selector must be declared in controls; assertions are executable visible-UI checks.",
            "publication_rule": "A generated card is visible only after the authoritative runner passes every test against the latest source hash.",
            "audit_boundary": "This materialization audit validates the executable contract and fixture hashes; Chromium evidence is produced only for a generated card in a real run.",
        },
        "cases": records,
    }
    _write_json(TESTDATA_ROOT / "_index.json", audit)
    readme = """# DemoPilot Core testdata\n\nEvery evaluation case has an isolated directory here. `inputs.json` describes the local fixture and exact paths; `acceptance.json` is the executable visible-UI acceptance contract; `manifest.json` records hashes. The Core Builder receives these paths in its prompt and may read them from its run workspace.\n\nThe invoice images are public, synthetic fixtures pinned by SHA-256 and copied into the invoice cases. Other cases use deterministic fixture records from the authored browser contract. This is a generation-loop evaluation dataset, not a claim of production integrations.\n"""
    (TESTDATA_ROOT / "README.md").write_text(readme, encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Materialize and fail if the audit is not complete")
    parser.parse_args()
    audit = materialize()
    complete = (
        audit["case_count"] == 20
        and audit["tier_counts"] == {"simple": 10, "medium": 5, "hard": 5}
        and all(item["status"] == "passed" and item["test_count"] > 0 and not item.get("issues") for item in audit["cases"])
    )
    print(json.dumps({"status": "passed" if complete else "failed", "case_count": audit["case_count"], "tier_counts": audit["tier_counts"], "invalid_cases": [item["case_id"] for item in audit["cases"] if item["status"] != "passed"]}, ensure_ascii=False))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
