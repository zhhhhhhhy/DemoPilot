from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .core_acceptance import run_acceptance
from .core_harness import HarnessAdapter
from .models import AgentEvent, AgentStatus, Artifact, DemoRun, RunStatus
from .storage import RunStore

CORE_AGENT_ROLE = "Core Builder（含验收子智能体）"
ACCEPTANCE_AGENT_ROLE = "确定性验收 Runner"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _emit(
    store: RunStore,
    run: DemoRun,
    agent_id: str,
    role: str,
    status: AgentStatus,
    message: str,
    iteration: int,
    *,
    event_type: str = "agent",
    payload: dict[str, Any] | None = None,
) -> None:
    run.last_event_sequence += 1
    run.events.append(
        AgentEvent(
            id=hashlib.sha256(f"{run.id}:{run.last_event_sequence}".encode()).hexdigest()[:24],
            agent_id=agent_id,
            role=role,
            status=status,
            message=message,
            iteration=iteration,
            event_type=event_type,  # type: ignore[arg-type]
            sequence=run.last_event_sequence,
            payload=payload or {},
        )
    )
    store.save(run)


def _copy_testdata(root: Path, workspace: Path, case_id: str) -> tuple[dict[str, str], str]:
    source = (root / "testdata" / case_id).resolve()
    if not source.is_dir():
        raise RuntimeError(f"testdata case is missing: {source}")
    target = workspace / "testdata" / case_id
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    protected: dict[str, str] = {}
    for name in ("inputs.json", "acceptance.json"):
        path = target / name
        protected[name] = _sha256(path)
    for path in target.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            protected[path.relative_to(target).as_posix()] = _sha256(path)
    return protected, str(target.relative_to(workspace).as_posix())


def _changed_files(workspace: Path) -> list[str]:
    return sorted(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file()
    )


def _unauthorized_files(workspace: Path, allowed_roots: list[Path]) -> list[str]:
    """Return files outside the three run-scoped roots the CLI may edit."""

    roots = [path.resolve() for path in allowed_roots]
    unauthorized: list[str] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not any(resolved == root or root in resolved.parents for root in roots):
            unauthorized.append(path.relative_to(workspace).as_posix())
    return sorted(unauthorized)


class CoreBuilderLoop:
    """Intent -> restricted CLI Builder -> deterministic acceptance -> publish."""

    def __init__(
        self,
        store: RunStore,
        harness: HarnessAdapter,
        *,
        project_root: Path,
        max_revision_rounds: int = 4,
    ) -> None:
        self.store = store
        self.harness = harness
        self.project_root = project_root.resolve()
        self.max_revision_rounds = max_revision_rounds

    def _goal_prompt(
        self,
        run: DemoRun,
        workspace: Path,
        case_id: str,
        iteration: int,
        feedback: list[str],
    ) -> str:
        request = run.request
        acceptance_path = f"testdata/{case_id}/acceptance.json"
        inputs_path = f"testdata/{case_id}/inputs.json"
        return f"""You are DemoPilot's Core Builder. This is iteration {iteration} of an evidence-driven goal loop.

GOAL
- Intent: {request.evaluation_intent or request.scenario}
- Goal: {request.evaluation_goal or request.priority}
- Business flow: {json.dumps(request.evaluation_flow_steps, ensure_ascii=False)}
- Expected result: {json.dumps(request.acceptance_criteria, ensure_ascii=False)}
- Must-have capabilities: {json.dumps(request.must_haves, ensure_ascii=False)}
- Case id: {case_id}; difficulty: {request.evaluation_difficulty or 'unspecified'}

AUTHORITATIVE INPUTS AND ACCEPTANCE
- Read the local fixture data at {inputs_path}.
- Read the executable visible-UI acceptance contract at {acceptance_path}.
- The contract contains the exact selectors, actions, values, and expected visible results. Treat it as the acceptance source of truth; do not invent a weaker test.
- Test data is part of this run and must be used from the stated relative paths. Never call an external OCR, database, API, or network resource.
- A project-local `acceptance_checker` agent definition is available under `.codex/agents/acceptance_checker.toml`. Before you report success, explicitly call the collaboration tool **`spawn_agent`** with `task_name=acceptance_checker` and wait for that child thread to finish (the display role is acceptance-checker; the underscore is required by the CLI agent-name contract). Do not call `wait` without first spawning the child, and do not treat your own check as a substitute. The subagent must inspect card-web, run `python "{self.project_root / 'scripts' / 'core_acceptance_cli.py'}" --workspace "{workspace}" --case-id {case_id}`, and report every failed selector or expected-result mismatch back to you. Repair the files and ask the same subagent to rerun when it fails. If spawning is unavailable, record that fact as a failed acceptance attempt; do not claim that a subagent test happened.

WRITE PERMISSION (HARD BOUNDARY)
- You may create or modify files only below {workspace / 'card'}, {workspace / 'card-web'}, and {workspace / 'testdata' / case_id}.
- Do not edit the repository, backend, frontend, evaluation_sets, acceptance.json, inputs.json, or pinned fixture bytes. Do not create files outside those three allowed roots.
- The acceptance script and publication decision are trusted harness code. You cannot mark a demo published and you cannot replace an acceptance result with a self-report.
- Build a runnable static card under card-web/index.html, card-web/styles.css, and card-web/app.js. Use relative local paths to the supplied testdata. Keep card/ for a readable card specification if useful.

ITERATION RULE
- Inspect the existing card-web from the previous iteration and repair it in place; preserve working behavior.
- Implement the complete goal and every acceptance path. A final message claiming completion is insufficient; the harness will run real Chromium after this turn.
- Return a short JSON object describing files changed and the subagent acceptance attempt. Do not include private reasoning.

Previous authoritative failures to repair:
{json.dumps(feedback, ensure_ascii=False)}
"""

    def _acceptance_child_prompt(self, *, workspace: Path, case_id: str) -> str:
        script = self.project_root / "scripts" / "core_acceptance_cli.py"
        return f"""You are the read-only acceptance_checker child inside DemoPilot's Core Builder loop.

Do not edit, create, delete, or rename any file. Do not publish anything and do not use a self-reported result.
Inspect the current card-web files and the authored contract under testdata/{case_id}. You MUST execute this exact
command with the command tool before answering:

python "{script}" --workspace "{workspace}" --case-id "{case_id}"

Return a short JSON object containing status, the command exit result, unresolved selectors, and repair advice. If the
command fails or cannot be run, return status=failed. The parent harness will verify the command_execution event and
exit code from your JSONL transcript, so a narrative claim cannot substitute for running the command.
"""

    async def execute(self, run: DemoRun) -> None:
        request = run.request
        case_id = request.evaluation_case_id
        if not case_id:
            raise RuntimeError("core_generation requires evaluation_case_id")
        run.status = RunStatus.RUNNING
        run.publication_status = "hidden"
        run.current_agent = "core-builder"
        run.progress = max(run.progress, 10)
        run.outputs["core_pipeline"] = {
            "stages": ["intent_acquisition", "core_builder_loop", "frontend_display"],
            "harness": self.harness.name,
            "independent_reviewer": False,
            "publication_rule": "publish only after deterministic Chromium acceptance passes",
        }
        run.outputs.setdefault("core_builder", {"adapter": self.harness.name, "iterations": []})
        run.checkpoint = "core:intent_acquired"
        self.store.save(run)

        core_root = self.store.run_dir(run.id) / "core-workspace"
        card = core_root / "card"
        card_web = core_root / "card-web"
        testdata = core_root / "testdata" / case_id
        card.mkdir(parents=True, exist_ok=True)
        card_web.mkdir(parents=True, exist_ok=True)
        protected, testdata_rel = _copy_testdata(self.project_root, core_root, case_id)
        baseline_acceptance_hash = protected["acceptance.json"]
        allowed_roots = [card, card_web, testdata]
        # A project-local agent definition makes the requested acceptance
        # child discoverable in non-interactive CLI runs. It is harness-owned,
        # read-only from the Builder's point of view, and never published.
        acceptance_agent_file = core_root / ".codex" / "agents" / "acceptance_checker.toml"
        acceptance_agent_file.parent.mkdir(parents=True, exist_ok=True)
        acceptance_agent_file.write_text(
            f"""name = "acceptance_checker"
description = "Read-only acceptance child for the current DemoPilot card."
sandbox_mode = "read-only"
model_reasoning_effort = "low"
developer_instructions = '''
You are the acceptance_checker child. Do not edit any files. Inspect the current card-web files and run:
python "{self.project_root / 'scripts' / 'core_acceptance_cli.py'}" --workspace "{core_root}" --case-id "{case_id}"
Return the command result, every failed selector or expected-result mismatch, and the exact repair advice to the parent.
'''
""",
            encoding="utf-8",
        )
        acceptance_agent_hash = _sha256(acceptance_agent_file)
        feedback: list[str] = []

        # Hash a small, explicit protected surface. The CLI never receives this
        # directory, but the digest makes the permission claim auditable.
        protected_core_files = [
            self.project_root / "backend" / "src" / "demopilot" / "models.py",
            self.project_root / "backend" / "src" / "demopilot" / "orchestrator.py",
            self.project_root / "frontend" / "src" / "App.vue",
        ]
        protected_core_hash = {str(path.relative_to(self.project_root)): _sha256(path) for path in protected_core_files}
        run.outputs["core_builder"]["workspace"] = {
            "relative_root": str(core_root.relative_to(self.store.run_dir(run.id))),
            "allowed_roots": [str(path.relative_to(core_root).as_posix()) for path in allowed_roots],
            "testdata_path": testdata_rel,
            "acceptance_agent": str(acceptance_agent_file.relative_to(core_root).as_posix()),
            "acceptance_agent_sha256": acceptance_agent_hash,
            "protected_core_sha256": protected_core_hash,
            "protected_acceptance_sha256": baseline_acceptance_hash,
        }
        self.store.save(run)

        for iteration in range(self.max_revision_rounds + 1):
            run.revision_count = iteration
            run.progress = min(90, 15 + iteration * 18)
            run.current_agent = "core-builder"
            _emit(self.store, run, "core-builder", CORE_AGENT_ROLE, AgentStatus.RUNNING, "正在按 Goal Prompt 生成或修复卡片，并要求验收子智能体先行检查", iteration)
            transcript_dir = self.store.run_dir(run.id) / "artifacts" / "evidence" / "core" / f"iteration-{iteration}"
            prompt = self._goal_prompt(run, core_root, case_id, iteration, feedback)
            session_record: dict[str, Any] = {"iteration": iteration, "status": "started", "transcript_dir": str(transcript_dir.relative_to(self.store.run_dir(run.id)))}
            try:
                harness_result = await self.harness.build(
                    request=request,
                    prompt=prompt,
                    workspace=core_root,
                    transcript_dir=transcript_dir,
                    allowed_roots=allowed_roots,
                    on_event=lambda event, i=iteration: self._on_harness_event(run, i, event),
                )
                session_record.update(harness_result)
                session_record["status"] = "completed"
            except Exception as exc:
                session_record.update({"status": "failed", "error": str(exc)[:500]})
                stdout_path = getattr(exc, "stdout_path", None)
                stderr_path = getattr(exc, "stderr_path", None)
                if stdout_path or stderr_path:
                    session_record["transcript"] = {
                        "prompt": str(transcript_dir / "prompt.txt"),
                        "stdout": str(stdout_path or transcript_dir / "stdout.jsonl"),
                        "stderr": str(stderr_path or transcript_dir / "stderr.log"),
                    }
            # Core-generation bypasses the legacy AgentProvider call wrapper,
            # so account for each real CLI process explicitly in the durable
            # run metric used by evaluation reports.
            run.agent_calls += 1

            # The current non-interactive Codex CLI may expose the
            # collaboration tool but emit an empty ``wait`` instead of a real
            # ``spawn_agent`` event, or spawn without recording the required
            # acceptance command. Keep native spawning plus command evidence
            # as the preferred path; otherwise invoke a separate read-only
            # CLI child in this same Core Builder iteration. This preserves
            # the required child boundary without introducing a legacy Reviewer.
            native_spawn_count = int(session_record.get("subagent_spawn_count", 0) or 0)
            native_command_passed = bool(session_record.get("acceptance_command_passed"))
            native_verified = native_spawn_count >= 1 and native_command_passed
            if not native_verified:
                _emit(
                    self.store,
                    run,
                    "acceptance",
                    ACCEPTANCE_AGENT_ROLE,
                    AgentStatus.RUNNING,
                    "CLI 未产生真实 spawn_agent，启动只读 acceptance_checker CLI 子进程复核",
                    iteration,
                    event_type="gate",
                    payload={"mode": "cli_child_fallback"},
                )
                checker = getattr(self.harness, "acceptance_check", None)
                child_dir = transcript_dir / "acceptance-child"
                child_record: dict[str, Any] = {
                    "status": "failed",
                    "mode": "cli_child_fallback",
                    "transcript_dir": str(child_dir.relative_to(self.store.run_dir(run.id))),
                }
                if checker is None:
                    child_record["error"] = "Harness adapter does not implement acceptance_check"
                else:
                    run.agent_calls += 1
                    try:
                        child_result = await checker(
                            prompt=self._acceptance_child_prompt(workspace=core_root, case_id=case_id),
                            workspace=core_root,
                            transcript_dir=child_dir,
                            readable_roots=[self.project_root / "scripts"],
                            on_event=lambda event, i=iteration: self._on_harness_event(run, i, event),
                        )
                        child_record.update(child_result)
                        command_passed = bool(child_result.get("acceptance_command_passed"))
                        child_record["status"] = "passed" if command_passed else "failed"
                        if not command_passed:
                            child_record["error"] = "acceptance child transcript has no completed core_acceptance_cli.py command with exit_code=0"
                    except Exception as exc:
                        child_record["error"] = str(exc)[:500]
                        stdout_path = getattr(exc, "stdout_path", None)
                        stderr_path = getattr(exc, "stderr_path", None)
                        if stdout_path or stderr_path:
                            child_record["transcript"] = {
                                "prompt": str(child_dir / "prompt.txt"),
                                "stdout": str(stdout_path or child_dir / "stdout.jsonl"),
                                "stderr": str(stderr_path or child_dir / "stderr.log"),
                            }
                session_record["acceptance_child"] = child_record
                _emit(
                    self.store,
                    run,
                    "acceptance",
                    ACCEPTANCE_AGENT_ROLE,
                    AgentStatus.COMPLETED if child_record.get("status") == "passed" else AgentStatus.FAILED,
                    "只读 acceptance_checker CLI 子进程已执行验收命令" if child_record.get("status") == "passed" else "只读 acceptance_checker CLI 子进程未执行成功验收命令",
                    iteration,
                    event_type="gate",
                    payload={"status": child_record.get("status"), "mode": "cli_child_fallback"},
                )

            run.outputs["core_builder"]["iterations"].append(session_record)
            self.store.save(run)

            # Immutable contract check occurs before Chromium and therefore
            # turns a prompt/model attempt into a repairable acceptance failure.
            acceptance_path = self.store.run_dir(run.id) / "artifacts" / "evidence" / "core" / f"iteration-{iteration}" / "acceptance.json"
            if _sha256(testdata / "acceptance.json") != baseline_acceptance_hash:
                acceptance = {
                    "status": "failed",
                    "case_id": case_id,
                    "checks": [],
                    "issues": ["CLI modified the protected acceptance contract"],
                    "changed_paths": _changed_files(core_root),
                    "source_sha256": {},
                    "acceptance_sha256": _sha256(testdata / "acceptance.json"),
                    "evidence": None,
                }
            else:
                _emit(self.store, run, "acceptance", ACCEPTANCE_AGENT_ROLE, AgentStatus.RUNNING, "正在用独立 Chromium 执行 testdata 中的验收路径", iteration, event_type="gate")
                evidence_path = self.store.run_dir(run.id) / "artifacts" / "evidence" / "core" / f"iteration-{iteration}" / "browser-evidence.png"
                acceptance = await __import__("asyncio").to_thread(
                    run_acceptance,
                    core_root,
                    case_id,
                    evidence_path,
                    protected,
                    {".codex/agents/acceptance_checker.toml"},
                )
                _emit(self.store, run, "acceptance", ACCEPTANCE_AGENT_ROLE, AgentStatus.COMPLETED if acceptance["status"] == "passed" else AgentStatus.FAILED, "Chromium 验收通过，允许发布" if acceptance["status"] == "passed" else "Chromium 验收失败，必须回送 Core Builder 返工", iteration, event_type="gate", payload={"status": acceptance["status"], "issue_count": len(acceptance.get("issues", []))})

            # A model's final JSON is not evidence that a child actually ran.
            # Prefer a recorded native spawn_agent collaboration event. The
            # explicit read-only CLI child above is the only accepted fallback.
            spawn_count = int(session_record.get("subagent_spawn_count", 0) or 0)
            acceptance["subagent_spawn_count"] = spawn_count
            child_record = session_record.get("acceptance_child", {})
            native_command_passed = bool(session_record.get("acceptance_command_passed"))
            native_spawn = spawn_count >= 1 and native_command_passed
            child_passed = isinstance(child_record, dict) and child_record.get("status") == "passed" and bool(child_record.get("acceptance_command_passed"))
            acceptance["subagent_execution_mode"] = "native_spawn" if native_spawn else "cli_child_fallback" if child_passed else "missing"
            acceptance["subagent_child"] = {
                "status": child_record.get("status") if isinstance(child_record, dict) else "missing",
                "acceptance_command_passed": bool(child_record.get("acceptance_command_passed")) if isinstance(child_record, dict) else False,
                "transcript": child_record.get("transcript") if isinstance(child_record, dict) else None,
            }
            unauthorized = _unauthorized_files(core_root, allowed_roots)
            harness_paths = {acceptance_agent_file.relative_to(core_root).as_posix()}
            unauthorized = [item for item in unauthorized if item not in harness_paths]
            acceptance["unauthorized_paths"] = unauthorized
            if not acceptance_agent_file.is_file() or _sha256(acceptance_agent_file) != acceptance_agent_hash:
                acceptance["status"] = "failed"
                acceptance.setdefault("issues", []).insert(0, "CLI modified the harness-owned acceptance_checker definition")
            if unauthorized:
                acceptance["status"] = "failed"
                acceptance.setdefault("issues", []).insert(
                    0,
                    "CLI wrote outside the allowed card, card-web and case testdata directories: "
                    + ", ".join(unauthorized[:8]),
                )
            if not native_spawn and not child_passed:
                acceptance["status"] = "failed"
                acceptance.setdefault("issues", []).insert(
                    0,
                    "Neither a native spawn_agent event nor a read-only acceptance_checker CLI child with a passing command was recorded; a self-reported child result is insufficient",
                )
                _emit(
                    self.store,
                    run,
                    "acceptance",
                    ACCEPTANCE_AGENT_ROLE,
                    AgentStatus.FAILED,
                    "未发现可复核的 acceptance_checker 子智能体验收证据，不能发布，必须返工",
                    iteration,
                    event_type="gate",
                    payload={"status": "failed", "reason": "missing_acceptance_child_evidence"},
                )
            acceptance_path.parent.mkdir(parents=True, exist_ok=True)
            acceptance_path.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            run.outputs["core_builder"]["iterations"][-1]["acceptance"] = acceptance
            run.outputs[f"core_acceptance_iteration_{iteration}"] = acceptance
            self._sync_evidence_artifacts(run)
            self.store.save(run)
            if acceptance["status"] == "passed":
                self._publish(run, core_root, protected_core_hash, iteration, acceptance)
                return
            feedback = [str(item) for item in acceptance.get("issues", [])]
            if not feedback:
                feedback = ["No acceptance evidence was produced; inspect the card-web files and rerun the contract."]
            if iteration < self.max_revision_rounds:
                _emit(self.store, run, "core-builder", CORE_AGENT_ROLE, AgentStatus.FAILED, "验收未通过，保留当前文件和全部证据，下一轮定向返工", iteration, event_type="gate", payload={"feedback": feedback[:8]})

        run.status = RunStatus.FAILED
        run.quality_gate = "failed"
        run.publication_status = "cannot_complete"
        run.current_agent = None
        run.progress = 100
        run.error = f"Core Builder 在 {self.max_revision_rounds + 1} 轮内未通过真实验收"
        run.checkpoint = "core:cannot_complete"
        self._sync_evidence_artifacts(run)
        self.store.save(run)

    def _on_harness_event(self, run: DemoRun, iteration: int, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        if event_type in {"process.started", "thread.started", "process.exited", "process.timeout"} or "collab" in event_type or "spawn" in event_type:
            _emit(self.store, run, "core-builder", CORE_AGENT_ROLE, AgentStatus.RUNNING, f"Codex CLI: {event_type}", iteration, payload={key: value for key, value in event.items() if key != "text"})

    def _publish(self, run: DemoRun, core_root: Path, protected_core_hash: dict[str, str], iteration: int, acceptance: dict[str, Any]) -> None:
        run_dir = self.store.run_dir(run.id)
        demo_root = run_dir / "artifacts" / "demo"
        demo_root.mkdir(parents=True, exist_ok=True)
        for path in (core_root / "card-web").iterdir():
            if path.is_file() and path.suffix.lower() in {".html", ".css", ".js"}:
                shutil.copy2(path, demo_root / path.name)
        publication = {
            "status": "published",
            "case_id": run.request.evaluation_case_id,
            "iteration": iteration,
            "acceptance_status": acceptance["status"],
            "tested_source_sha256": acceptance.get("source_sha256", {}),
            "protected_core_sha256": protected_core_hash,
            "harness": self.harness.name,
            "reviewer": "not_used_in_core_loop",
        }
        publication_path = run_dir / "artifacts" / "evidence" / "core" / "publication.json"
        publication_path.parent.mkdir(parents=True, exist_ok=True)
        publication_path.write_text(json.dumps(publication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run.outputs["publication"] = publication
        run.publication_status = "published"
        run.quality_gate = "passed"
        run.status = RunStatus.COMPLETED
        run.progress = 100
        run.current_agent = None
        run.checkpoint = "core:published"
        run.artifacts = []
        for name in ("index.html", "styles.css", "app.js"):
            run.artifacts.append(Artifact(name=name, kind="demo", relative_path=f"artifacts/demo/{name}", download_url=f"/api/runs/{run.id}/files/artifacts/demo/{name}"))
        self._sync_evidence_artifacts(run)
        self.store.save(run)

    def _sync_evidence_artifacts(self, run: DemoRun) -> None:
        """Expose retained prompts, JSONL, stderr and gate reports to the UI."""
        run_dir = self.store.run_dir(run.id)
        evidence_root = run_dir / "artifacts" / "evidence" / "core"
        existing = {item.relative_path for item in run.artifacts}
        for path in sorted(evidence_root.rglob("*")) if evidence_root.exists() else []:
            if not path.is_file():
                continue
            relative = path.relative_to(run_dir).as_posix()
            if relative in existing:
                continue
            run.artifacts.append(
                Artifact(
                    name=path.name,
                    kind="evidence",
                    relative_path=relative,
                    download_url=f"/api/runs/{run.id}/files/{relative}",
                )
            )
