from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "backend" / "src"))

from demopilot.generator import generate_artifacts  # noqa: E402
from demopilot.models import DemoRun  # noqa: E402
from demopilot.verifier import verify_artifacts  # noqa: E402


def replay(run_id: str, project_dir: Path) -> dict[str, object]:
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise ValueError(f"Invalid run id: {run_id}")
    source = project_dir / ".data" / "runs" / run_id / "run.json"
    run = DemoRun.model_validate_json(source.read_text(encoding="utf-8"))
    output_dir = project_dir / ".data" / "replays" / run_id
    generate_artifacts(run, output_dir)
    validation = verify_artifacts(run, output_dir)
    app_js = (output_dir / "artifacts" / "demo" / "app.js").read_text(encoding="utf-8")
    match = re.search(r"const data = (\{.*?\});\s*let current", app_js, re.DOTALL)
    app_data = json.loads(match.group(1)) if match else {}
    return {
        "run_id": run_id,
        "provider": run.request.provider,
        "validation": validation["status"],
        "issues": validation["issues"],
        "story": app_data.get("story", []),
        "features": app_data.get("features", []),
        "output_dir": str(output_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay stored DemoPilot model outputs")
    parser.add_argument("run_ids", nargs="+")
    args = parser.parse_args()
    results = [replay(run_id, PROJECT_DIR) for run_id in args.run_ids]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
