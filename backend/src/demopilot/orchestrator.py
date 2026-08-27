from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from .browser_qa import verify_browser_interactions
from .builder_preflight import preflight_builder_output
from .generator import generate_artifacts
from .harness import SandboxViolation, SandboxWorkspace
from .interaction_contract import compile_interaction_contract
from .models import AgentEvent, AgentStatus, ApprovalRequest, Artifact, DemoRun, RunStatus
from .providers import AgentProvider
from .reviewer import normalize_final_review, normalize_review_rubric
from .skill_runtime import SkillProfile, SkillRegistry
from .storage import RunStore
from .verifier import verify_artifacts


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    id: str
    role: str
    progress: int
    start_message: str
    done_message: str


AGENTS = {
    item.id: item
    for item in (
        AgentDefinition("brief", "需求增强 Agent", 10, "正在补全 Demo Brief 与缺失假设", "可执行 Demo Brief 已形成"),
        AgentDefinition("manager", "团队经理 Agent", 20, "正在拆解目标、依赖与验收标准", "协作计划与调用预算已确定"),
        AgentDefinition("discovery", "需求洞察 Agent", 32, "正在识别业务问题与成功标准", "客户问题与价值假设已对齐"),
        AgentDefinition("product", "产品策划 Agent", 50, "正在设计三幕 Demo 故事", "功能范围与演示主线已生成"),
        AgentDefinition("experience", "体验设计 Agent", 50, "正在构建视觉语言与交互层级", "苹果风格体验规范已完成"),
        AgentDefinition("contract", "交互契约 Agent", 60, "正在固化页面、控件与验收路径", "内部共享交互协议已冻结"),
        AgentDefinition("builder", "Demo 构建 Agent", 70, "正在组装页面、数据与交互", "第一版 Demo 已构建"),
        AgentDefinition("runner", "产物验证 Agent", 82, "正在检查生成文件与运行边界", "最终产物已完成本地验证"),
        AgentDefinition("reviewer", "独立评审 Agent", 94, "正在对照需求、项目与运行证据进行独立评审", "评审结论、根因与复验方法已记录"),
    )
}


class ApprovalRequired(RuntimeError):
    pass


class RunCancelled(RuntimeError):
    pass


class DemoOrchestrator:
    def __init__(
        self,
        store: RunStore,
        providers: dict[str, AgentProvider],
        *,
        max_agent_calls: int = 18,
        max_revision_rounds: int = 4,
        max_parallel_agents: int = 2,
        skill_registry: SkillRegistry | None = None,
    ):
        self.store = store
        self.providers = providers
        self.max_agent_calls = max_agent_calls
        self.max_revision_rounds = max_revision_rounds
        self.parallel_limit = asyncio.Semaphore(max_parallel_agents)
        self.skill_registry = skill_registry or SkillRegistry()

    @staticmethod
    def _context_for_agent(
        run: DemoRun,
        agent_id: str,
        *,
        iteration: int = 0,
        phase: str | None = None,
    ) -> dict[str, Any]:
        """Return only the evidence an agent needs instead of the whole run history.

        A completed run contains duplicate aliases, every prior review, validation output,
        and (for builders) tens of thousands of characters of source files. Sending all of
        that back to every model call made revisions slow and increased truncation risk.
        """

        keys_by_agent = {
            "brief": (),
            "manager": ("brief",),
            "discovery": ("brief", "manager"),
            "product": ("brief", "manager", "discovery"),
            "experience": ("brief", "manager", "discovery"),
            "contract": (
                "discovery",
                "product",
                "experience",
                "review_rubric",
            ),
        }
        if agent_id in keys_by_agent:
            keys = keys_by_agent[agent_id]
        elif agent_id == "builder":
            keys = (
                "discovery",
                "product",
                "experience",
                "review_rubric",
                "interaction_contract",
                *(('revision_feedback',) if iteration else ()),
            )
        elif agent_id == "reviewer" and phase == "rubric":
            keys = ("brief", "manager", "discovery")
        elif agent_id == "reviewer":
            keys = (
                "product",
                "experience",
                "review_rubric",
                "interaction_contract",
                "builder",
                "build_provenance",
                "artifact_validation",
            )
        else:
            keys = tuple(run.outputs)

        context = {key: run.outputs[key] for key in keys if key in run.outputs}
        if agent_id == "reviewer" and phase == "rubric":
            context["review_phase"] = {"mode": "rubric"}
        if agent_id == "builder" and iteration and "builder" in run.outputs:
            # The next Builder must emit complete replacement files, so only retain the
            # previous implementation summary; the failing evidence lives in feedback.
            previous = run.outputs["builder"]
            if isinstance(previous, dict):
                context["previous_builder_summary"] = {
                    key: value for key, value in previous.items() if key != "files"
                }
        return context

    def _event(
        self,
        run: DemoRun,
        agent_id: str,
        status: AgentStatus,
        message: str,
        *,
        iteration: int = 0,
        event_type: str = "agent",
        payload: dict[str, Any] | None = None,
    ) -> None:
        agent = AGENTS[agent_id]
        run.last_event_sequence += 1
        run.events.append(
            AgentEvent(
                id=uuid.uuid4().hex,
                agent_id=agent.id,
                role=agent.role,
                status=status,
                message=message,
                iteration=iteration,
                event_type=event_type,
                sequence=run.last_event_sequence,
                payload=payload or {},
            )
        )
        self.store.save(run)

    @staticmethod
    def _check_cancel(run: DemoRun) -> None:
        if run.cancel_requested:
            raise RunCancelled("任务已由用户取消")

    async def _provider_call(
        self,
        run: DemoRun,
        agent_id: str,
        context: dict[str, Any],
        *,
        iteration: int = 0,
        skill_stage: str | None = None,
    ) -> dict[str, Any]:
        self._check_cancel(run)
        if run.agent_calls >= self.max_agent_calls:
            raise RuntimeError("Agent call budget exhausted")
        run.agent_calls += 1
        runtime = run.outputs.setdefault("skill_runtime", {"profile": "approved"})
        requested_profile = str(runtime.get("profile", "approved"))
        if requested_profile not in {"baseline", "candidate", "approved"}:
            raise RuntimeError(f"Unknown Skill profile: {requested_profile}")
        profile: SkillProfile = requested_profile  # type: ignore[assignment]
        stage = skill_stage or agent_id
        skills = self.skill_registry.select(profile, stage, iteration=iteration)
        packet = self.skill_registry.packet(skills)
        context = {**context, "__engineering_skills__": packet}
        trace = run.outputs.setdefault("skill_trace", {"calls": []})
        trace["calls"].append(
            {
                "call": run.agent_calls,
                "agent": agent_id,
                "stage": stage,
                "iteration": iteration,
                "profile": profile,
                "skill_names": [skill.name for skill in skills],
                "bundle_sha256": packet["bundle_sha256"],
            }
        )
        self.store.save(run)
        provider = self.providers[run.request.provider]
        async with self.parallel_limit:
            result = await provider.run_agent(
                agent_id,
                run.request,
                context,
                iteration=iteration,
            )
        latest = self.store.get(run.id)
        if latest and latest.cancel_requested:
            run.cancel_requested = True
        self._check_cancel(run)
        return result

    def _store_output(
        self,
        run: DemoRun,
        agent_id: str,
        result: dict[str, Any],
        iteration: int,
    ) -> None:
        if agent_id in {"builder", "reviewer"}:
            run.outputs[f"{agent_id}_iteration_{iteration}"] = result
        run.outputs[agent_id] = result
        run.checkpoint = f"agent:{agent_id}:iteration:{iteration}"
        self.store.save(run)

    async def _run_agent(
        self,
        run: DemoRun,
        agent_id: str,
        *,
        iteration: int = 0,
        start_message: str | None = None,
        done_message: str | None = None,
    ) -> dict[str, Any]:
        agent = AGENTS[agent_id]
        run.current_agent = agent_id
        run.progress = max(run.progress, max(4, agent.progress - 7))
        self._event(
            run,
            agent_id,
            AgentStatus.RUNNING,
            start_message or agent.start_message,
            iteration=iteration,
        )
        result = await self._provider_call(
            run,
            agent_id,
            self._context_for_agent(run, agent_id, iteration=iteration),
            iteration=iteration,
        )
        self._store_output(run, agent_id, result, iteration)
        run.progress = max(run.progress, agent.progress)
        self._event(
            run,
            agent_id,
            AgentStatus.COMPLETED,
            done_message or agent.done_message,
            iteration=iteration,
        )
        return result

    async def _run_parallel_design(self, run: DemoRun) -> None:
        include_reviewer = "review_rubric" not in run.outputs
        agent_ids = (
            ("product", "experience", "reviewer")
            if include_reviewer
            else ("product", "experience")
        )
        run.current_agent = "+".join(agent_ids)
        run.progress = max(run.progress, 40)
        for agent_id in agent_ids:
            message = (
                "正在把客户需求转成独立评审标准"
                if agent_id == "reviewer"
                else AGENTS[agent_id].start_message
            )
            self._event(
                run,
                agent_id,
                AgentStatus.RUNNING,
                message,
                event_type="lifecycle" if agent_id == "reviewer" else "agent",
                payload={"phase": "rubric"} if agent_id == "reviewer" else None,
            )
        contexts = [
            self._context_for_agent(
                run,
                agent_id,
                phase="rubric" if agent_id == "reviewer" else None,
            )
            for agent_id in agent_ids
        ]
        results = await asyncio.gather(
            *(
                self._provider_call(
                    run,
                    agent_id,
                    agent_context,
                    skill_stage="reviewer:rubric" if agent_id == "reviewer" else agent_id,
                )
                for agent_id, agent_context in zip(agent_ids, contexts, strict=True)
            )
        )
        for agent_id, result in zip(agent_ids, results, strict=True):
            if agent_id == "reviewer":
                run.outputs["review_rubric"] = normalize_review_rubric(
                    run.request, result
                )
                run.checkpoint = "agent:reviewer:rubric"
                self.store.save(run)
                self._event(
                    run,
                    agent_id,
                    AgentStatus.COMPLETED,
                    "独立评审标准与硬门禁已形成",
                    event_type="lifecycle",
                    payload={"phase": "rubric"},
                )
            else:
                self._store_output(run, agent_id, result, 0)
                self._event(
                    run, agent_id, AgentStatus.COMPLETED, AGENTS[agent_id].done_message
                )
        run.progress = max(run.progress, 50)
        self.store.save(run)

    async def _prepare_review_rubric(self, run: DemoRun) -> dict[str, Any]:
        if "review_rubric" in run.outputs:
            return run.outputs["review_rubric"]
        run.current_agent = "reviewer"
        self._event(
            run,
            "reviewer",
            AgentStatus.RUNNING,
            "正在把客户需求转成独立评审标准",
            event_type="lifecycle",
            payload={"phase": "rubric"},
        )
        context = self._context_for_agent(run, "reviewer", phase="rubric")
        result = await self._provider_call(
            run, "reviewer", context, skill_stage="reviewer:rubric"
        )
        rubric = normalize_review_rubric(run.request, result)
        run.outputs["review_rubric"] = rubric
        run.checkpoint = "agent:reviewer:rubric"
        self.store.save(run)
        self._event(
            run,
            "reviewer",
            AgentStatus.COMPLETED,
            "独立评审标准与硬门禁已形成",
            event_type="lifecycle",
            payload={"phase": "rubric"},
        )
        return rubric

    async def _run_reviewer(
        self,
        run: DemoRun,
        validation: dict[str, Any],
        *,
        iteration: int,
    ) -> dict[str, Any]:
        reviewer = AGENTS["reviewer"]
        run.current_agent = "reviewer"
        run.progress = max(run.progress, reviewer.progress - 7)
        self._event(
            run,
            "reviewer",
            AgentStatus.RUNNING,
            reviewer.start_message,
            iteration=iteration,
            payload={"phase": "final", "evidence_bound": True},
        )
        raw_review = await self._provider_call(
            run,
            "reviewer",
            self._context_for_agent(run, "reviewer", iteration=iteration, phase="final"),
            iteration=iteration,
            skill_stage="reviewer:final",
        )
        review = normalize_final_review(
            run.request,
            raw_review,
            validation,
            run.outputs["review_rubric"],
        )
        self._store_output(run, "reviewer", review, iteration)
        # Compatibility alias for existing artifact consumers; new code uses reviewer.
        run.outputs["qa"] = review
        run.outputs[f"qa_iteration_{iteration}"] = review
        run.progress = max(run.progress, reviewer.progress)
        self._event(
            run,
            "reviewer",
            AgentStatus.COMPLETED,
            reviewer.done_message,
            iteration=iteration,
            payload={
                "phase": "final",
                "decision": review["decision"],
                "score": review["overall_score"],
                "issue_count": len(review["issues"]),
            },
        )
        return review

    @staticmethod
    def _approved_parallel_design(manager_result: dict[str, Any]) -> bool:
        groups = manager_result.get("parallel_groups")
        if not isinstance(groups, list):
            return False
        for group in groups:
            values: list[object]
            if isinstance(group, list):
                values = group
            elif isinstance(group, dict) and isinstance(group.get("workstreams"), list):
                values = group["workstreams"]
            else:
                continue
            normalized: set[str] = set()
            for value in values:
                if not isinstance(value, str):
                    continue
                lowered = value.lower()
                if "product" in lowered:
                    normalized.add("product")
                if "experience" in lowered or "design" in lowered:
                    normalized.add("experience")
            if {"product", "experience"}.issubset(normalized):
                return True
        return False

    async def _verify_with_browser(
        self,
        run: DemoRun,
        validation: dict[str, Any],
        workspace: SandboxWorkspace,
    ) -> dict[str, Any]:
        browser = await verify_browser_interactions(
            run.id, self.store.run_dir(run.id), workspace
        )
        validation["browser_e2e"] = browser
        validation["checks"].extend(browser.get("checks", []))
        validation["issues"].extend(browser.get("issues", []))
        validation["status"] = "passed" if not validation["issues"] else "failed"
        if browser.get("status") == "passed" and not any(
            artifact.kind == "evidence" for artifact in run.artifacts
        ):
            run.artifacts.append(
                Artifact(
                    name="Chromium 交互验证截图",
                    kind="evidence",
                    relative_path="artifacts/qa/browser-evidence.png",
                    download_url=(
                        f"/api/runs/{run.id}/files/artifacts/qa/browser-evidence.png"
                    ),
                )
            )
        return validation

    async def _generate_and_verify(
        self, run: DemoRun, *, iteration: int
    ) -> dict[str, Any]:
        self._check_cancel(run)
        run.current_agent = "runner"
        run.progress = max(run.progress, 76)
        message = "正在重新生成并验证修订产物" if iteration else AGENTS["runner"].start_message
        self._event(run, "runner", AgentStatus.RUNNING, message, iteration=iteration)
        workspace = SandboxWorkspace(
            run, self.store.run_dir(run.id), on_change=self.store.save
        )
        try:
            run.artifacts = generate_artifacts(
                run, self.store.run_dir(run.id), workspace=workspace
            )
            validation = verify_artifacts(run, self.store.run_dir(run.id))
            validation = await self._verify_with_browser(run, validation, workspace)
        except SandboxViolation as exc:
            # A blocked write is proof that the Builder needs revision, not an
            # orchestrator outage. Preserve the failed receipt and let Reviewer
            # turn the evidence into actionable feedback without weakening the Hook.
            issue = f"安全 Hook 拒绝 Builder 产物：{exc}"
            validation = {
                "status": "failed",
                "source_mode": run.outputs.get("build_provenance", {}).get(
                    "source_mode", "unknown"
                ),
                "fixed_contract": {
                    "artifact_type": "controlled_static_sales_demo",
                    "intentional_non_goals": [
                        "真实系统集成",
                        "真实领域数据写入",
                        "生产鉴权与部署",
                    ],
                },
                "checks": ["任务级沙箱与预写入安全 Hook 正常工作"],
                "issues": [issue],
                "feature_coverage": {
                    "required": list(run.request.must_haves),
                    "rendered": [],
                    "missing": list(run.request.must_haves),
                },
                "interaction_coverage": {},
                "manifest": [],
                "browser_e2e": {
                    "status": "skipped",
                    "reason": "产物在写入前被安全 Hook 阻断",
                },
            }
        workspace.record_validation(validation)
        run.outputs["artifact_validation"] = validation
        run.outputs[f"artifact_validation_iteration_{iteration}"] = validation
        run.checkpoint = f"artifacts:iteration:{iteration}"
        run.progress = max(run.progress, AGENTS["runner"].progress)
        self._event(
            run,
            "runner",
            AgentStatus.COMPLETED,
            (
                "安全 Hook 已阻断问题产物，等待 Reviewer 触发返工"
                if validation["issues"]
                else AGENTS["runner"].done_message
            ),
            iteration=iteration,
        )
        return validation

    def _ensure_execution_approval(self, run: DemoRun) -> None:
        action = "sandbox_generate"
        approval = next(
            (item for item in reversed(run.approvals) if item.action == action), None
        )
        if approval and approval.status in {"approved", "auto_approved"}:
            return
        if approval and approval.status == "declined":
            raise RunCancelled("沙箱生成审批已拒绝")
        if not run.request.require_execution_approval:
            run.approvals.append(
                ApprovalRequest(
                    id=uuid.uuid4().hex,
                    action=action,
                    reason="仅在当前任务目录生成静态 Demo 与交付包",
                    risk="low",
                    requested_by="runner",
                    status="auto_approved",
                )
            )
            self._event(
                run,
                "runner",
                AgentStatus.COMPLETED,
                "低风险任务级沙箱写入已按策略自动批准",
                event_type="approval",
                payload={"action": action, "decision": "auto_approved"},
            )
            return
        if approval is None:
            approval = ApprovalRequest(
                id=uuid.uuid4().hex,
                action=action,
                reason="Builder 已完成方案，等待批准后在当前任务沙箱写入 HTML/CSS/JS 与 ZIP",
                risk="low",
                requested_by="runner",
            )
            run.approvals.append(approval)
            self._event(
                run,
                "runner",
                AgentStatus.WAITING,
                "等待人工批准任务级沙箱生成",
                event_type="approval",
                payload={"approval_id": approval.id, "action": action},
            )
        run.status = RunStatus.WAITING_APPROVAL
        run.current_agent = "runner"
        run.checkpoint = "waiting_approval:sandbox_generate"
        self.store.save(run)
        raise ApprovalRequired("等待人工审批")

    @staticmethod
    def _needs_revision(qa: dict[str, Any], validation: dict[str, Any]) -> bool:
        return bool(validation.get("issues")) or qa.get("decision") == "revise"

    @staticmethod
    def _preflight_validation(run: DemoRun, preflight: dict[str, Any]) -> dict[str, Any]:
        messages = [
            str(item.get("message", "Builder 预检失败"))
            for item in preflight.get("issues", [])
            if isinstance(item, dict)
        ]
        return {
            "status": "failed",
            "source_mode": preflight.get("mode", "agent_generated_files"),
            "fixed_contract": {
                "artifact_type": "controlled_static_sales_demo",
                "intentional_non_goals": [
                    "真实系统集成",
                    "真实领域数据写入",
                    "生产鉴权与部署",
                ],
            },
            "checks": list(preflight.get("checks", [])),
            "issues": messages or ["Builder 确定性预检失败"],
            "feature_coverage": {
                "required": list(run.request.must_haves),
                "rendered": [],
                "missing": list(run.request.must_haves),
            },
            "interaction_coverage": {},
            "manifest": [],
            "browser_e2e": {
                "status": "skipped",
                "reason": "Builder 未通过低成本确定性预检，未启动 Chromium",
            },
            "builder_preflight": preflight,
        }

    async def _run_builder_preflight(self, run: DemoRun) -> dict[str, Any]:
        """Repair objective Builder failures before approval, disk writes and browser."""

        evaluation_trace = run.outputs.get("evaluation_trace", {})
        if (
            isinstance(evaluation_trace, dict)
            and evaluation_trace.get("builder_preflight_enabled") is False
        ):
            iteration = run.revision_count
            preflight = {
                "status": "disabled",
                "blocking": False,
                "mode": "evaluation_control_group",
                "checks": [],
                "issues": [],
                "failure_classes": [],
                "contract_sha256": run.outputs.get("interaction_contract", {}).get(
                    "contract_sha256"
                ),
                "evaluation_only": True,
            }
            run.outputs["builder_preflight"] = preflight
            run.outputs[f"builder_preflight_iteration_{iteration}"] = preflight
            run.checkpoint = f"builder:preflight-disabled:iteration:{iteration}"
            self._event(
                run,
                "builder",
                AgentStatus.COMPLETED,
                "A/B 对照组已关闭 Builder 预检；普通 Demo 不受影响",
                iteration=iteration,
                event_type="gate",
                payload={
                    "gate": "builder_preflight",
                    "status": "disabled",
                    "evaluation_only": True,
                    "browser_started": False,
                },
            )
            return preflight

        while True:
            iteration = run.revision_count
            preflight = preflight_builder_output(run)
            run.outputs["builder_preflight"] = preflight
            run.outputs[f"builder_preflight_iteration_{iteration}"] = preflight
            run.checkpoint = f"builder:preflight:iteration:{iteration}"
            self._event(
                run,
                "builder",
                AgentStatus.COMPLETED,
                (
                    "Builder 确定性预检通过，主观质量留给 Reviewer"
                    if not preflight.get("blocking")
                    else "Builder 确定性预检阻断，已生成定向返修清单"
                ),
                iteration=iteration,
                event_type="gate",
                payload={
                    "gate": "builder_preflight",
                    "status": preflight.get("status"),
                    "failure_classes": preflight.get("failure_classes", []),
                    "browser_started": False,
                },
            )
            if not preflight.get("blocking"):
                return preflight

            first_pass_only = bool(
                run.outputs.get("evaluation_trace", {}).get("first_pass_only")
            )
            if first_pass_only or iteration >= self.max_revision_rounds:
                return preflight

            run.revision_count = iteration + 1
            run.outputs["revision_feedback"] = {
                "stage": "builder_preflight",
                "failure_classes": preflight.get("failure_classes", []),
                "issues": preflight.get("issues", []),
                "repair_policy": (
                    "只修复列出的确定性问题并返回三个完整替换文件；"
                    "不得改写冻结契约或放宽安全规则。"
                ),
                "contract_sha256": preflight.get("contract_sha256"),
            }
            self.store.save(run)
            await self._run_agent(
                run,
                "builder",
                iteration=iteration + 1,
                start_message="预检发现确定性错误，Builder 正在定向修复",
                done_message="Builder 已返回预检修订版",
            )

    async def execute(self, run_id: str) -> None:
        run = self.store.get(run_id)
        if not run:
            return
        run.status = RunStatus.RUNNING
        run.progress = max(run.progress, 4)
        run.error = None
        self.store.save(run)
        try:
            if "brief" not in run.outputs:
                await self._run_agent(run, "brief")
            if "manager" not in run.outputs:
                await self._run_agent(run, "manager")
            manager_result = run.outputs["manager"]
            parallel_design = self._approved_parallel_design(manager_result)
            if "workflow_plan" not in run.outputs:
                run.outputs["workflow_plan"] = {
                    "stages": [
                        ["brief"],
                        ["manager"],
                        ["discovery"],
                        (["product", "experience", "reviewer:rubric"] if parallel_design else ["product"]),
                        *([] if parallel_design else [["experience"]]),
                        *([] if parallel_design else [["reviewer:rubric"]]),
                        ["contract"],
                        ["builder"],
                        ["builder:preflight"],
                        ["approval"],
                        ["runner"],
                        ["reviewer:final"],
                    ],
                    "parallel_design": parallel_design,
                    "max_agent_calls": self.max_agent_calls,
                    "max_revision_rounds": self.max_revision_rounds,
                    "recovery": "checkpoint_resume",
                    "event_transport": "sse",
                }
                self.store.save(run)
            if "discovery" not in run.outputs:
                await self._run_agent(run, "discovery")
            missing_design = {
                agent_id for agent_id in ("product", "experience") if agent_id not in run.outputs
            }
            if missing_design == {"product", "experience"} and parallel_design:
                await self._run_parallel_design(run)
            else:
                for agent_id in ("product", "experience"):
                    if agent_id in missing_design:
                        await self._run_agent(run, agent_id)
            if "review_rubric" not in run.outputs:
                await self._prepare_review_rubric(run)
            if "interaction_contract" not in run.outputs:
                raw_contract = await self._run_agent(run, "contract")
                run.outputs["interaction_contract_raw"] = raw_contract
                run.outputs["interaction_contract"] = compile_interaction_contract(
                    run.request, raw_contract
                )
                run.checkpoint = "agent:contract:compiled"
                self.store.save(run)
            if "builder" not in run.outputs:
                await self._run_agent(run, "builder")

            preflight = await self._run_builder_preflight(run)
            blocked_by_preflight = bool(preflight.get("blocking"))
            if not blocked_by_preflight:
                self._ensure_execution_approval(run)

            final_review: dict[str, Any] = {}
            final_validation: dict[str, Any] = {}
            iteration = run.revision_count
            while iteration <= self.max_revision_rounds:
                validation_key = f"artifact_validation_iteration_{iteration}"
                reviewer_key = f"reviewer_iteration_{iteration}"
                if validation_key in run.outputs:
                    final_validation = run.outputs[validation_key]
                elif blocked_by_preflight and iteration == run.revision_count:
                    final_validation = self._preflight_validation(run, preflight)
                    run.outputs["artifact_validation"] = final_validation
                    run.outputs[validation_key] = final_validation
                    self.store.save(run)
                else:
                    final_validation = await self._generate_and_verify(
                        run, iteration=iteration
                    )
                if reviewer_key in run.outputs:
                    final_review = run.outputs[reviewer_key]
                else:
                    final_review = await self._run_reviewer(
                        run, final_validation, iteration=iteration
                    )
                if not self._needs_revision(final_review, final_validation):
                    break
                if run.outputs.get("evaluation_trace", {}).get("first_pass_only"):
                    break
                if iteration >= self.max_revision_rounds:
                    raise RuntimeError("Quality gate failed after the allowed revision rounds")
                run.revision_count = iteration + 1
                run.outputs["revision_feedback"] = {
                    "reviewer": final_review,
                    "qa": final_review,
                    "artifact_validation": final_validation,
                }
                self.store.save(run)
                await self._run_agent(
                    run,
                    "builder",
                    iteration=iteration + 1,
                    start_message="Reviewer 要求返工，正在修订页面、数据与交互",
                    done_message="Reviewer 反馈已处理，修订版 Demo 已构建",
                )
                preflight = await self._run_builder_preflight(run)
                blocked_by_preflight = bool(preflight.get("blocking"))
                iteration = run.revision_count

            self._check_cancel(run)
            if run.outputs.get("evaluation_trace", {}).get("first_pass_only"):
                open_gates = final_review.get("open_gates") or []
                if self._needs_revision(final_review, final_validation):
                    run.quality_gate = "failed"
                else:
                    run.quality_gate = (
                        "passed_with_open_gates" if open_gates else "passed"
                    )
                run.status = RunStatus.COMPLETED
                run.progress = 100
                run.current_agent = None
                run.checkpoint = "completed:first_pass_only"
                self.store.save(run)
                return
            workspace = SandboxWorkspace(
                run, self.store.run_dir(run.id), on_change=self.store.save
            )
            run.artifacts = generate_artifacts(
                run, self.store.run_dir(run.id), workspace=workspace
            )
            final_validation = verify_artifacts(run, self.store.run_dir(run.id))
            final_validation = await self._verify_with_browser(
                run, final_validation, workspace
            )
            workspace.record_validation(final_validation)
            run.outputs["artifact_validation"] = final_validation
            if final_validation.get("issues"):
                raise RuntimeError("Final artifact verification failed")
            open_gates = final_review.get("open_gates") or []
            run.quality_gate = "passed_with_open_gates" if open_gates else "passed"
            run.status = RunStatus.COMPLETED
            run.progress = 100
            run.current_agent = None
            run.checkpoint = "completed"
            self.store.save(run)
        except ApprovalRequired:
            return
        except RunCancelled as exc:
            run.status = RunStatus.CANCELLED
            run.current_agent = None
            run.error = str(exc)
            run.checkpoint = "cancelled"
            active_agent_id = (run.current_agent or "runner").split("+")[-1]
            self._event(
                run,
                active_agent_id if active_agent_id in AGENTS else "runner",
                AgentStatus.CANCELLED,
                "任务已取消，已完成的检查点和调用凭证仍保留",
                iteration=run.revision_count,
                event_type="lifecycle",
            )
            self.store.save(run)
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.current_agent = None
            run.error = "任务已由用户取消"
            run.checkpoint = "cancelled"
            self._event(
                run,
                "runner",
                AgentStatus.CANCELLED,
                "任务已取消，已完成的检查点和调用凭证仍保留",
                iteration=run.revision_count,
                event_type="lifecycle",
            )
            self.store.save(run)
        except Exception as exc:  # background boundary: persist a safe user-visible failure
            active_agent_id = (run.current_agent or "reviewer").split("+")[-1]
            if active_agent_id not in AGENTS:
                active_agent_id = "reviewer"
            run.status = RunStatus.FAILED
            run.quality_gate = "failed"
            run.current_agent = None
            run.error = str(exc)[:500]
            self._event(
                run,
                active_agent_id,
                AgentStatus.FAILED,
                "生成中断，请检查模型配置、调用预算或输入",
                iteration=run.revision_count,
            )
            self.store.save(run)
