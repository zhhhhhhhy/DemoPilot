"""Read-only acceptance probe used by Core Builder subagents.

The authoritative browser runner lives in ``demopilot.core_acceptance``. This
command deliberately performs static/path checks only so a delegated subagent
can inspect the same contract without being able to publish a result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    root = args.workspace.resolve()
    acceptance_path = root / "testdata" / args.case_id / "acceptance.json"
    card_root = root / "card-web"
    if not acceptance_path.is_file():
        print(json.dumps({"status": "failed", "issue": "acceptance.json missing"}))
        return 1
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    required = [card_root / name for name in ("index.html", "styles.css", "app.js")]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing or not acceptance.get("tests"):
        print(json.dumps({"status": "failed", "missing": missing, "test_count": len(acceptance.get("tests", []))}))
        return 1
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in required)
    selectors = {
        str(step.get("selector"))
        for test in acceptance["tests"]
        if isinstance(test, dict)
        for step in test.get("steps", [])
        if isinstance(step, dict)
    }
    unresolved = [selector for selector in selectors if selector.startswith("#") and selector[1:] not in text]
    status = "passed" if not unresolved else "failed"
    print(json.dumps({"status": status, "case_id": args.case_id, "test_count": len(acceptance["tests"]), "unresolved_selectors": unresolved}, ensure_ascii=False))
    return 0 if not unresolved else 1


if __name__ == "__main__":
    raise SystemExit(main())
