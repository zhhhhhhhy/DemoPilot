"""Compare old/new browser gates on copied, real development CLI artifacts.

This is a controlled detector check, with no model calls and no final cases.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from demopilot.quotation_browser import audit_application, tree_hash  # noqa: E402

MUTATIONS = {
    "stale_record_form": """
;(() => {
  const ids = ['profile','product','quantity','second-product','second-quantity',
               'customer','date','manual-rate','shipping'];
  let previous = {};
  document.addEventListener('change', event => {
    if (event.target.id !== 'record') return;
    previous = Object.fromEntries(ids.filter(id => document.getElementById(id))
      .map(id => [id, document.getElementById(id).value]));
  }, true);
  document.addEventListener('change', event => {
    if (event.target.id !== 'record') return;
    for (const [id,value] of Object.entries(previous))
      document.getElementById(id).value = value;
  });
})();
""",
    "missing_rejection_message": """
;window.addEventListener('click', () => {
  const error = document.getElementById('error');
  if (error) error.textContent = '';
});
""",
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def development_only(source, contract):
    identifier = contract["id"]
    if identifier.startswith("sales-v3-"):
        development = json.loads((ROOT / "evaluation_sets/sales-benchmark-v3/split.json").read_text("utf-8"))["development"]
        if identifier not in development:
            raise ValueError("Only development cases are authorized for fault calibration")
    elif identifier.startswith("qflow-"):
        relative = source.relative_to(ROOT / "evaluation_sets/quotation-reliability-v2/results")
        if identifier not in relative.parts or not relative.parts[0].startswith(("development-", "pilot-")):
            raise ValueError("Legacy qflow artifact must have explicit development/pilot provenance")
    else:
        raise ValueError("Unrecognized development contract provenance")


def old_browser(revision, output):
    raw = subprocess.check_output(
        ["git", "show", f"{revision}:backend/src/demopilot/quotation_browser.py"], cwd=ROOT,
    )
    path = output / f"legacy-browser-{revision}.py"
    path.write_bytes(raw)
    name = "demopilot._field_assertion_legacy_browser"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, hashlib.sha256(raw).hexdigest()


async def main(args):
    source, output = args.source.resolve(), args.output.resolve()
    contract = json.loads(args.contract.read_text("utf-8"))
    development_only(source, contract)
    if args.profile:
        contract["profiles"] = {args.profile: contract["profiles"][args.profile]}
    # Refuse an entire existing directory, so partial attempts also survive.
    output.mkdir(parents=True, exist_ok=False)
    source_hash = tree_hash(source)
    legacy, legacy_hash = old_browser(args.old_revision, output)
    rows = []
    for name, patch in [("valid_control", None), *MUTATIONS.items()]:
        app = output / name / "app"
        app.parent.mkdir(parents=True)
        shutil.copytree(source, app)
        if patch:
            javascript = app / "app.js"
            javascript.write_text(javascript.read_text("utf-8") + "\n" + patch, encoding="utf-8")
        app_hash = tree_hash(app)
        for gate, audit in [("old", legacy.audit_application), ("new", audit_application)]:
            report = await audit(app, contract, output / name / gate, private=False)
            expected = "failed" if patch and gate == "new" else "passed"
            row = {
                "name": name, "gate": gate, "expected": expected, "actual": report["status"],
                "correct": report["status"] == expected,
                "planned": report["planned_journeys"], "executed": report["executed_journeys"],
                "passed": report["passed_journeys"], "app_sha256": app_hash,
                "source_unchanged": report["source_unchanged"], "issues": report["issues"],
            }
            rows.append(row)
            write_json(output / "progress.json", {"rows": rows})
            print(json.dumps(row, ensure_ascii=False), flush=True)
        if patch is None and any(not row["correct"] for row in rows):
            break
    summary = {
        "kind": "controlled-development-detector-calibration-not-model-accuracy",
        "source_cli_artifact": str(source), "source_sha256": source_hash,
        "source_unchanged": source_hash == tree_hash(source),
        "legacy_revision": args.old_revision, "legacy_browser_sha256": legacy_hash,
        "new_browser_sha256": hashlib.sha256((ROOT / "backend/src/demopilot/quotation_browser.py").read_bytes()).hexdigest(),
        "contract_source": str(args.contract.resolve()), "profile_subset": list(contract["profiles"]),
        "vector_mode": "public-prepublication", "cli_calls": 0, "final_cases_executed": 0,
        "all_expected": len(rows) == 6 and all(row["correct"] for row in rows), "rows": rows,
        "boundary": "Copied real CLI development artifact with two seeded UI corruptions; no model trials, no estimated real-world accuracy, no historical score replacement.",
    }
    write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--old-revision", default="e6bed15")
    parser.add_argument("--profile")
    result = asyncio.run(main(parser.parse_args()))
    raise SystemExit(0 if result["all_expected"] else 1)
