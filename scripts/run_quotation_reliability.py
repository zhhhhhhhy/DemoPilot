"""Frozen equal-information CLI generation/change comparison, complete100 combos."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from demopilot.core_harness import CodexCliHarness
from demopilot.quotation_cli import IsolatedCodexProvider, isolation_flags
from demopilot.quotation_browser import audit_application, tree_hash
from demopilot.quotation_loop import QuotationGoalLoop, write_json
from demopilot.quotation_release import ReleaseRegistry
from demopilot.quotation_contract import compile_acceptance

DATASET = ROOT / "evaluation_sets/quotation-reliability-v2"
CODE = [
    "backend/src/demopilot/quotation_contract.py",
    "backend/src/demopilot/quotation_browser.py",
    "backend/src/demopilot/quotation_release.py",
    "backend/src/demopilot/quotation_loop.py",
    "backend/src/demopilot/quotation_api.py",
    "backend/src/demopilot/quotation_cli.py",
    "scripts/quotation_business_probe.py",
    "scripts/run_quotation_reliability.py",
    "scripts/run_with_awake.py",
    "backend/src/demopilot/core_harness.py",
    "backend/src/demopilot/providers/codex_cli.py",
    "backend/src/demopilot/models.py",
]


def read(p):
    return json.loads(Path(p).read_text("utf-8"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def context(split):
    apps = [a for a in read(DATASET / "apps.json")["apps"] if a["split"] == split]
    order = [[app["id"], arm] for app in apps for arm in ("direct", "reliable")]
    random.Random(71641).shuffle(order)
    for app in apps:
        for version in (1, 2):
            cfg = read(ROOT / app["testdata_path"] / f"contract-v{version}.json")
            for private in (False, True):
                plan = (
                    DATASET / "private" / f"{app['id']}-v{version}.json"
                    if private
                    else ROOT / app["testdata_path"] / f"public-tests-v{version}.json"
                )
                if compile_acceptance(cfg, private=private) != read(plan):
                    raise RuntimeError("Acceptance compiler/plan drift: " + str(plan))
    return dict(
        schema_version="quotation-reliability-v2.2",
        cohort_boundary=("Full paired runtime-corrected replication of the same seven primary groups after prior outcomes were known; reused inputs, not new blind requirements." if split == "heldout" else "Development groups; not primary."),
        split=split,
        apps=apps,
        arm_order=order,
        model="gpt-6.1-sol",
        reasoning_effort="medium",
        cli_timeout_seconds=300,
        call_cap_per_version=3,
        max_parallel=2,
        audit_parallelism=2,
        versions=[1, 2],
        identical_business_information=True,
        baseline_public_probe_access=True,
        cli_isolation_flags=isolation_flags(),
        independent_unit="workflow_application_group",
        combination_count=len(apps) * 10,
        source_sha256={p: sha(ROOT / p) for p in CODE},
        data_sha256=read(DATASET / "manifest.json")["files"],
        private_protocol="quotation_contract.journeys(private=True): frozen before CLI. Independent fresh-context browser scoring after ALL terminal outcomes; no feedback or post-score repairs.",
        budget="Equal configured caps, not forced equal usage. Native acceptance subagent activity and token totals are separately retained; outer calls are not billed cost.",
    )


def validate(output, split):
    frozen = read(output / "context.json")
    current = context(split)
    if current != frozen:
        raise RuntimeError("Code, data or protocol changed since freeze")
    for p, h in frozen["data_sha256"].items():
        if sha(ROOT / p) != h:
            raise RuntimeError("Frozen dataset changed: " + p)
    return frozen


async def execute(output, split):
    frozen = validate(output, split)
    apps = {a["id"]: a for a in frozen["apps"]}
    slots = asyncio.Semaphore(frozen["max_parallel"])
    lock = asyncio.Lock()
    rows = []
    registries = {
        arm: ReleaseRegistry(output / "registries" / arm, require_business=arm == "reliable")
        for arm in ("direct", "reliable")
    }

    async def one(app_id, arm):
        async with slots:
            validate(output, split)
            app = apps[app_id]
            target = output / app_id / arm
            workspace = target / "workspace"
            provider = IsolatedCodexProvider(
                command="codex",
                model=frozen["model"],
                reasoning_effort=frozen["reasoning_effort"],
                timeout_seconds=frozen["cli_timeout_seconds"],
                cwd=ROOT,
            )
            loop = QuotationGoalLoop(
                CodexCliHarness(provider),
                registries[arm],
                project_root=ROOT,
                call_cap=frozen["call_cap_per_version"],
            )
            for version in frozen["versions"]:
                row = await loop.execute_version(
                    app=app, version=version, arm=arm, workspace=workspace, result_dir=target
                )
                async with lock:
                    rows.append(row)
                    write_json(
                        output / "results-progress.json",
                        dict(
                            rows=rows,
                            planned_app_arms=len(frozen["arm_order"]),
                            planned_versions=len(frozen["arm_order"]) * 2,
                        ),
                    )
                print(
                    json.dumps(
                        dict(
                            app_id=app_id,
                            arm=arm,
                            version=version,
                            status=row["status"],
                            cli_calls=row["cli_calls"],
                            repairs=row["internal_repair_rounds"],
                            elapsed=row["elapsed_seconds"],
                        )
                    ),
                    flush=True,
                )

    await asyncio.gather(*(one(*entry) for entry in frozen["arm_order"]))
    write_json(
        output / "results.json",
        dict(
            real_cli=True,
            rows=rows,
            planned_combinations=frozen["combination_count"],
            versions=2,
            app_arms=len(frozen["arm_order"]),
        ),
    )


async def audit(output, split):
    frozen = validate(output, split)
    results = read(output / "results.json")["rows"]
    if len(results) != len(frozen["arm_order"]) * 2:
        raise RuntimeError("Every planned app/version must be terminal before independent scoring")
    dest = output / "independent-audit.json"
    if dest.exists():
        raise RuntimeError("Refuse overwrite of independent score")
    rows = []
    slots = asyncio.Semaphore(frozen["audit_parallelism"])
    lock = asyncio.Lock()

    async def one(result):
        async with slots:
            app = next(a for a in frozen["apps"] if a["id"] == result["app_id"])
            contract = read(ROOT / app["testdata_path"] / f"contract-v{result['version']}.json")
            report = await audit_application(
                result["terminal_candidate_path"],
                contract,
                output
                / "independent-audit"
                / result["app_id"]
                / result["arm"]
                / f"v{result['version']}",
                private=True,
            )
            report.update(
                arm=result["arm"],
                split=split,
                published=result["status"] == "published",
                end_to_end_pass=result["status"] == "published" and report["status"] == "passed",
                cli_calls=result["cli_calls"],
                internal_repairs=result["internal_repair_rounds"],
            )
            if tree_hash(result["terminal_candidate_path"]) != result["terminal_sha256"]:
                raise RuntimeError("Terminal candidate bytes changed")
            async with lock:
                rows.append(report)
                write_json(
                    output / "independent-audit-progress.json",
                    dict(rows=rows, feedback_to_builder=False),
                )
            print(
                json.dumps(
                    dict(
                        app_id=result["app_id"],
                        arm=result["arm"],
                        version=result["version"],
                        published=report["published"],
                        functional=report["status"],
                        passed=report["passed_journeys"],
                        planned=report["planned_journeys"],
                    )
                ),
                flush=True,
            )

    await asyncio.gather(*(one(result) for result in results))
    rows.sort(key=lambda r: (r["app_id"], r["arm"], r["version"]))
    write_json(
        dest,
        dict(
            created_at=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            feedback_to_builder=False,
            all_planned=True,
        ),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--split", required=True, choices=["development", "heldout"])
    m = p.add_mutually_exclusive_group(required=True)
    for name in ("freeze", "real", "audit"):
        m.add_argument("--" + name, action="store_true")
    a = p.parse_args()
    output = a.output_dir.resolve()
    if a.freeze:
        if (output / "context.json").exists():
            raise RuntimeError("Refuse existing context overwrite")
        frozen = context(a.split)
        write_json(output / "context.json", frozen)
        write_json(
            output / "freeze-record.json",
            dict(
                time=datetime.now(timezone.utc).isoformat(),
                context_sha256=sha(output / "context.json"),
                real_runs=False,
            ),
        )
        for relative in frozen["source_sha256"]:
            dest = output / "frozen-code" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, dest)
        print(
            json.dumps(
                dict(
                    frozen=True,
                    app_groups=len(frozen["apps"]),
                    combinations=frozen["combination_count"],
                    arms=2,
                    versions=2,
                )
            )
        )
    elif a.real:
        asyncio.run(execute(output, a.split))
    else:
        asyncio.run(audit(output, a.split))


if __name__ == "__main__":
    main()
