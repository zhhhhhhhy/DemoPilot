"""Recheck all repaired published cards after browser-runner maintenance."""
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from demopilot.core_acceptance import run_acceptance


def main():
    base = ROOT / "evaluation_sets/sales-business-v2/results/20261016"
    output = ROOT / "docs/portfolio-v1/evidence/runner-replay"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in json.loads((base / "results.json").read_text(encoding="utf-8"))["results"]:
        source = ROOT / ".data/runs" / row["run_id"]
        card = source / "artifacts/demo"
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in card.iterdir() if path.is_file()}
        with tempfile.TemporaryDirectory(prefix="demopilot-runner-replay-") as temp:
            workspace = Path(temp)
            shutil.copytree(card, workspace / "card-web")
            shutil.copytree(source / "core-workspace/testdata" / row["case_id"], workspace / "testdata" / row["case_id"])
            started = time.perf_counter()
            result = run_acceptance(workspace, row["case_id"], output / f"{row['case_id']}.png")
            elapsed = time.perf_counter() - started
        unchanged = before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in card.iterdir() if path.is_file()}
        rows.append({"case_id": row["case_id"], "run_id": row["run_id"], "status": result["status"], "checks": result["checks"], "issues": result["issues"], "seconds": round(elapsed, 3), "original_card_unchanged": unchanged})
        report = {"rows": rows, "passed_journeys": sum(len(item["checks"]) for item in rows), "model_calls": 0}
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case_id": row["case_id"], "status": result["status"], "seconds": round(elapsed, 3)}), flush=True)
    if len(rows) != 3 or report["passed_journeys"] != 24 or not all(row["status"] == "passed" and row["original_card_unchanged"] for row in rows):
        raise SystemExit("Required full regression is not complete")


if __name__ == "__main__":
    main()
