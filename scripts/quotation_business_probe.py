"""Public business probe available identically to both experiment arms."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from demopilot.quotation_browser import audit_application

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", type=int, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    evidence = workspace / "card" / f"selfcheck-v{args.version}"
    evidence.mkdir(parents=True, exist_ok=True)
    contract = json.loads((workspace / "testdata" / f"contract-v{args.version}.json").read_text("utf-8"))
    # This is an isolated probe process. Runtime fallback logs belong to its
    # allowed card folder; never change CWD in the concurrent parent auditor.
    os.chdir(workspace / "card")
    result = asyncio.run(audit_application(workspace / "card-web", contract, evidence, private=False))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)
