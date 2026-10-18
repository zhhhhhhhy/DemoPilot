"""Versioned, harness-independent Goal loop for the v2 reliability experiment.

Additive successor to CoreBuilderLoop: old frozen experiments remain runnable.
Only the adapter generates/edits a demo. The controller stages immutable output,
checks the declared contract, and returns machine findings to the same builder.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from .models import DemoRequest
from .quotation_browser import audit_application, structural_check, tree_hash
from .quotation_release import ReleaseRegistry


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class QuotationGoalLoop:
    def __init__(self, harness, registry: ReleaseRegistry, *, project_root, call_cap=3):
        self.harness = harness
        self.registry = registry
        self.root = Path(project_root)
        self.call_cap = call_cap

    async def execute_version(self, *, app, version, arm, workspace, result_dir):
        workspace = Path(workspace)
        result_dir = Path(result_dir)
        result_file = result_dir / f"result-v{version}.json"
        if result_file.exists():
            return json.loads(result_file.read_text("utf-8"))
        if (result_dir / f"active-v{version}.json").exists():
            raise RuntimeError(
                "Interrupted nonterminal job requires diagnosis; automatic duplicate launch prohibited"
            )
        data = workspace / "testdata"
        data.mkdir(parents=True, exist_ok=True)
        original_data = self.root / app["testdata_path"]
        # v2 information is unavailable to the model until the change is requested.
        shutil.copy2(
            original_data / f"contract-v{version}.json", data / f"contract-v{version}.json"
        )
        shutil.copy2(
            original_data / f"public-tests-v{version}.json", data / f"public-tests-v{version}.json"
        )
        contract_text = (original_data / "CONTRACT.md").read_text("utf-8")
        contract_text = (
            contract_text.split("Subsequent version2 request")[0]
            + "\nSelf acceptance: run the public business probe, then repair failures within this call budget. Retain command outputs in card/acceptance.md."
        )
        (data / "CONTRACT.md").write_text(contract_text, encoding="utf-8")
        for name in ("card", "card-web"):
            (workspace / name).mkdir(exist_ok=True)
        contract = json.loads((data / f"contract-v{version}.json").read_text("utf-8"))
        if version >= 2:
            contract_text += "\nNEW REQUIREMENT v2: add #shipping select pickup/standard/express default pickup; freight0/20/50 per whole quote, added ONCE AFTER pricing discounts and tax. It participates in total and approval threshold; committing shipping changes invalidates approval and increments revision/history once. Preserve ALL v1 price profiles and behavior for pickup. Provide #freight output with two decimals. Work in the existing v1 source, not a separate throwaway app."
        project = app["id"]
        job_id = f"{project}-{arm}-v{version}"
        self.registry.set_intent(project, version, contract)
        job = self.registry.claim(project, version, job_id)
        write_json(
            result_dir / f"active-v{version}.json",
            dict(job_id=job_id, project=project, version=version, arm=arm, status="running"),
        )
        # Immutable public fixtures and outside runtime hashes protect the write boundary.
        input_digest = tree_hash(data)
        protected_files = [
            *list((self.root / "backend/src/demopilot").rglob("*.py")),
            self.root / "scripts/quotation_business_probe.py",
        ]
        protected_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_files}
        request = DemoRequest(
            client_name="合成报价样例",
            project_name="可验收报价工作流",
            industry="B2B",
            scenario="基于完整业务规则构建并迭代本地报价与审批应用。",
            audience="销售与审批人员",
            provider="codex_cli",
        )
        prompt = f"""You are a bounded implementation worker in parent transaction TX-ac2e52deb104.
Parent state: {self.root / "docs/quotation-reliability-v2/WORKFLOW_STATE.json"}. The parent has already completed preflight, routing and execute gates and owns the attempt ledger. As allowed by the engineering workflow worker protocol, return your commands/results to the parent; DO NOT initialize another workflow controller or write your own workflow state. Focus the budget on the application and real self-tests. No extra planning report is needed.
Goal: implement the complete local quotation application {project}, requirement version {version}. Prioritize complete business correctness and executable checks; a clean compact layout is sufficient. Avoid elaborate animation or long design documents.
Context: read testdata/CONTRACT.md and testdata/contract-v{version}.json. They contain ALL business rules and test data, identical between comparison arms. testdata/public-tests-v{version}.json contains inspectable public action sequences and exact expected visible results. All these fixtures are immutable. No missing-fact inference is required.
Monetary precision policy: retain full precision through aggregation, percentage discounts and total arithmetic; then round EACH displayed money field independently half-up to two decimals. Do not compute Total by subtracting already rounded display strings. Generic illustrative example outside the benchmark fixtures:12.35 with10% discount displays Discount1.24 and Total11.12 under final-aggregate rounding. Tax-inclusive net Subtotal is the explicitly stated exception rounded before residual Tax. The same policy and full information are given to both arms.
{contract_text}
Allowed writes: ONLY card/ and card-web/ within {workspace}. testdata/ is READ ONLY. Never change project core, harness, parent directories, evaluator, browser binaries, credentials, or prior evidence. No external requests or packages. Keep all artifacts self-contained. Do not read evaluation_sets, private cases or expected outputs. The CLI sandbox is the workspace; the controller additionally checks fixture integrity.
Output: card-web/index.html, card-web/app.js, card-web/styles.css; card/acceptance.md with actual self-test commands/results. No generated implementation is supplied.
Evaluation method available identically to both arms: execute the public read-only business probe via PowerShell:
& '{self.root / "backend/.venv/Scripts/python.exe"}' -X utf8 '{self.root / "scripts/quotation_business_probe.py"}' --workspace '{workspace}' --version {version}
The probe writes its evidence ONLY to card/selfcheck-v{version}; do not edit the probe. You may use a read-only acceptance subagent if helpful. Independently exercise every price profile and this workflow's positive, invalid, role, edit and multi-record paths. Rework until all goals are achieved or accurately report what remains unsatisfied. No external reviewer will manually repair your code.
"""
        iterations = []
        started = time.monotonic()
        feedback = []
        published = None
        for iteration in range(self.call_cap):
            transcript = result_dir / f"v{version}" / f"iteration-{iteration}"
            this_prompt = (
                prompt
                + "\nParent findings from the preceding attempt (repair without breaking passing behavior):\n"
                + json.dumps(feedback, ensure_ascii=False)
            )
            error = None
            cli_result = {}
            try:
                cli_result = await self.harness.build(
                    request=request,
                    prompt=this_prompt,
                    workspace=workspace,
                    transcript_dir=transcript / "cli",
                    allowed_roots=[workspace / "card", workspace / "card-web"],
                )
            except Exception as exc:
                error = dict(type=type(exc).__name__, message=str(exc)[:1500])
            boundary_ok = tree_hash(data) == input_digest
            core_changes = [
                str(p.relative_to(self.root))
                for p, h in protected_hashes.items()
                if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h
            ]
            outside = [
                p.relative_to(workspace).as_posix()
                for p in workspace.iterdir()
                if p.name not in ("card", "card-web", "testdata")
            ]
            engineering = structural_check(workspace / "card-web")
            if not boundary_ok:
                engineering["issues"].append("Read-only testdata changed")
            if core_changes:
                engineering["issues"].append("Protected core changed: " + str(core_changes))
            if outside:
                engineering["issues"].append("Writes outside allowed folders: " + str(outside))
            if engineering["issues"]:
                engineering["status"] = "failed"
            digest = tree_hash(workspace / "card-web")
            check = dict(engineering, source_sha256=digest, source_unchanged=True)
            if engineering["status"] == "passed" and arm == "reliable":
                check = await audit_application(
                    workspace / "card-web", contract, transcript / "business-check", private=False
                )
            # Timeout/CLI error is not a model's terminal claim of completion.
            if error:
                check = dict(
                    check,
                    status="failed",
                    issues=[*check.get("issues", []), "CLI did not complete: " + str(error)],
                )
            check_id = self.registry.record_check(
                job_id,
                job["token"],
                digest,
                check,
                kind="business" if arm == "reliable" else "engineering-control",
            )
            row = dict(
                iteration=iteration,
                cli_error=error,
                cli_result=cli_result,
                engineering=engineering,
                check=check,
                artifact_sha256=digest,
            )
            iterations.append(row)
            write_json(transcript / "iteration.json", row)
            if check["status"] == "passed":
                published = self.registry.publish(
                    job_id, job["token"], check_id, workspace / "card-web"
                )
                break
            feedback = check.get("issues", []) or ["Acceptance failed; inspect retained evidence"]
            if not boundary_ok or outside or core_changes:
                break
        result = dict(
            app_id=project,
            workflow=app["workflow"],
            split=app["split"],
            arm=arm,
            version=version,
            status="published" if published else "cannot_complete",
            published=published,
            iterations=iterations,
            cli_calls=len(iterations),
            internal_repair_rounds=max(0, len(iterations) - 1),
            elapsed_seconds=round(time.monotonic() - started, 3),
            workspace=str(workspace),
            candidate_path=str(workspace / "card-web"),
            terminal_sha256=tree_hash(workspace / "card-web"),
            private_audit_feedback=False,
        )
        if not published:
            self.registry.fail(
                job_id,
                job["token"],
                "Configured call budget exhausted or protected boundary changed",
            )
        # Snapshot also failed terminal candidates so later v2 edits cannot rewrite v1.
        terminal = result_dir / f"terminal-v{version}"
        shutil.copytree(workspace / "card-web", terminal)
        result["terminal_candidate_path"] = str(terminal)
        write_json(result_file, result)
        write_json(
            result_dir / f"active-v{version}.json",
            dict(job_id=job_id, status="terminal", result=str(result_file)),
        )
        return result
