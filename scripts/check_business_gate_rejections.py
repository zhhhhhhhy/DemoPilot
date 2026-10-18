"""Verify the strengthened gate rejects retained out-of-contract artifacts.

All checks use temporary copies. Original runs and generated files stay intact.
The lead example is a clarified global-list requirement, not proven data loss.
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from demopilot.core_acceptance import run_acceptance

SAMPLES = {
    "simple-quote-generator-01": "6ba9414d84b5",
    "medium-lead-followup-01": "56b546934e42",
    "hard-procurement-approval-01": "cb2ecd9f94ff",
}


def hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir() if path.is_file()}


def main():
    output = ROOT / "docs/portfolio-v1/evidence/gate-rejections"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for case_id, run_id in SAMPLES.items():
        source = ROOT / ".data/runs" / run_id / "artifacts/demo"
        before = hashes(source)
        with tempfile.TemporaryDirectory(prefix="demopilot-business-gate-") as temp:
            workspace = Path(temp)
            shutil.copytree(source, workspace / "card-web")
            shutil.copytree(ROOT / "evaluation_sets/sales-business-v2/testdata" / case_id, workspace / "testdata" / case_id)
            result = run_acceptance(workspace, case_id, output / f"{case_id}.png")
        rows.append({"case_id": case_id, "old_run_id": run_id, "new_gate_status": result["status"], "issues": result["issues"], "old_artifact_unchanged": before == hashes(source)})
        (output / "results.json").write_text(json.dumps({"rows": rows, "not_an_intent_ab": True}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case_id": case_id, "new_gate_status": result["status"]}), flush=True)
    if not all(row["new_gate_status"] == "failed" and row["old_artifact_unchanged"] for row in rows):
        raise SystemExit("New gate did not reject a target or original bytes changed")


if __name__ == "__main__":
    main()
