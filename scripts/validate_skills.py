from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from demopilot.skill_runtime import SkillRegistry  # noqa: E402


def main() -> int:
    registry = SkillRegistry()
    report = {
        profile: registry.describe_profile(profile)
        for profile in ("baseline", "candidate", "approved")
    }
    stages = (
        "brief",
        "discovery",
        "product",
        "experience",
        "contract",
        "reviewer:rubric",
        "builder",
        "reviewer:final",
    )
    report["candidate_routes"] = {
        stage: [skill.name for skill in registry.select("candidate", stage)]
        for stage in stages
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
