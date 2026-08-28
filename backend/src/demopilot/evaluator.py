from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections import Counter
from typing import Any

from . import __version__
from .evaluation_cases import builtin_evaluation_cases
from .evaluation_models import (
    AcceptanceGate,
    ComplexityMetrics,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationMetrics,
    EvaluationRun,
)
from .evaluation_store import EvaluationStore
from .models import DemoRequest, DemoRun, RunStatus, utc_now
from .runtime import TERMINAL_STATUSES, RunManager
from .storage import RunStore


def _feature_coverage(validation: dict[str, Any]) -> float:
    coverage = validation.get("feature_coverage", {})
    required = coverage.get("required", []) if isinstance(coverage, dict) else []
    missing = coverage.get("missing", []) if isinstance(coverage, dict) else []
    if not required:
        return 1.0
    return max(0.0, (len(required) - len(missing)) / len(required))


def _failure_category(run: DemoRun, issues: list[str]) -> str:
    if run.status == RunStatus.CANCELLED:
        return "cancelled"
    preflight = run.outputs.get("builder_preflight", {})
    if isinstance(preflight, dict) and preflight.get("blocking"):
        classes = set(preflight.get("failure_classes", []))
        if "security" in classes:
            return "preflight_security"
        if classes & {"selector", "control_type", "assertion", "action_binding", "contract"}:
            return "interaction_contract"
        if "data_contract" in classes:
            return "data_contract"
        return "builder_preflight"
    text = " ".join([run.error or "", *issues]).lower()
    if "provider" in text or "http 4" in text or "api" in text and "request" in text:
        return "provider"
    if "budget" in text or "调用预算" in text:
        return "budget"
    if "hook" in text or "沙箱" in text or "密钥" in text:
        return "sandbox"
    if "chromium" in text or "浏览器" in text:
        return "browser"
    if "artifact" in text or "产物" in text or "viewport" in text or "能力未进入" in text:
        return "artifact_contract"
    if "quality gate" in text or "质量" in text or "revision" in text:
        return "quality_gate"
    return "unknown"


def _first_pass_snapshot(run: DemoRun) -> dict[str, Any]:
    validation = run.outputs.get("artifact_validation_iteration_0", {})
    reviewer = run.outputs.get("reviewer_iteration_0", {})
    browser = validation.get("browser_e2e", {}) if isinstance(validation, dict) else {}
    validation_issues = validation.get("issues", []) if isinstance(validation, dict) else []
    reviewer_issues = reviewer.get("issues", []) if isinstance(reviewer, dict) else []
    source_mode = str(
        run.outputs.get("build_provenance", {}).get("source_mode")
        or run.outputs.get("builder_preflight", {}).get("mode")
        or "unknown"
    )
    artifact_pass = validation.get("status") == "passed"
    browser_pass = browser.get("status") == "passed"
    coverage = _feature_coverage(validation)
    security_pass = artifact_pass and not any(
        marker in " ".join(str(item) for item in validation_issues).lower()
        for marker in ("外部网络", "cookie", "密钥", "远程资源")
    )
    provenance_pass = (
        source_mode == "controlled_template_fallback"
        if run.request.provider == "mock"
        else source_mode == "agent_generated_files"
    )
    decision = str(reviewer.get("decision", "revise"))
    evidence_score = (
        20 * artifact_pass
        + 20 * browser_pass
        + 25 * coverage
        + 15 * security_pass
        + 20 * provenance_pass
    )
    try:
        reviewer_score = min(100.0, max(0.0, float(reviewer.get("overall_score", 0))))
    except (TypeError, ValueError):
        reviewer_score = 0.0
    passed = bool(
        artifact_pass
        and browser_pass
        and coverage == 1
        and security_pass
        and provenance_pass
        and decision in {"pass", "pass_with_open_gates"}
        and not validation_issues
        and not reviewer_issues
    )
    return {
        "passed": passed,
        "score": round(max(0.0, min(float(evidence_score), reviewer_score)), 2),
        "browser_status": str(browser.get("status", "not_run")),
    }


def evaluate_demo_run(case: EvaluationCase, run: DemoRun) -> EvaluationCaseResult:
    validation = run.outputs.get("artifact_validation", {})
    browser = validation.get("browser_e2e", {}) if isinstance(validation, dict) else {}
    validation_issues = validation.get("issues", []) if isinstance(validation, dict) else []
    reviewer = run.outputs.get("reviewer") or run.outputs.get("qa", {})
    reviewer_issues = reviewer.get("issues", [])
    normalized_review_issues = [
        str(item.get("evidence") or item.get("message") or "")
        if isinstance(item, dict)
        else str(item)
        for item in reviewer_issues
    ]
    issues = [
        str(item)
        for item in [*validation_issues, *normalized_review_issues]
        if str(item).strip()
    ]
    if run.error:
        issues.insert(0, run.error)
    source_mode = str(
        run.outputs.get("build_provenance", {}).get("source_mode")
        or run.outputs.get("builder_preflight", {}).get("mode")
        or "unknown"
    )
    artifact_pass = validation.get("status") == "passed"
    browser_pass = browser.get("status") == "passed"
    coverage = _feature_coverage(validation)
    security_pass = artifact_pass and not any(
        marker in " ".join(validation_issues).lower()
        for marker in ("外部网络", "cookie", "密钥", "远程资源")
    )
    provenance_pass = (
        source_mode == "controlled_template_fallback"
        if run.request.provider == "mock"
        else source_mode == "agent_generated_files"
    )
    completed = run.status == RunStatus.COMPLETED
    reviewer_decision = str(
        reviewer.get("decision", "pass" if not reviewer_issues else "revise")
    )
    evidence_score = (
        25 * completed
        + 20 * artifact_pass
        + 15 * browser_pass
        + 20 * coverage
        + 10 * security_pass
        + 10 * provenance_pass
    )
    reviewer_score = reviewer.get("overall_score", evidence_score)
    try:
        reviewer_score = min(100.0, max(0.0, float(reviewer_score)))
    except (TypeError, ValueError):
        reviewer_score = float(evidence_score)
    efficiency_deduction = min(
        10.0,
        2.0 * run.revision_count + 0.25 * max(0, run.agent_calls - 9),
    )
    score = max(0.0, min(float(evidence_score), reviewer_score) - efficiency_deduction)
    passed = bool(
        completed
        and artifact_pass
        and browser_pass
        and coverage == 1
        and security_pass
        and provenance_pass
        and reviewer_decision in {"pass", "pass_with_open_gates"}
        and run.quality_gate in {"passed", "passed_with_open_gates"}
    )
    first_pass = _first_pass_snapshot(run)
    category = "none" if passed else _failure_category(run, issues)
    return EvaluationCaseResult(
        case_id=case.id,
        case_name=case.name,
        complexity=case.complexity,
        run_id=run.id,
        status="passed" if passed else ("cancelled" if run.status == RunStatus.CANCELLED else "failed"),
        passed=passed,
        score=round(float(score), 2),
        failure_category=category,
        issues=issues[:12],
        source_mode=source_mode,
        artifact_status=str(validation.get("status", "not_run")),
        browser_status=str(browser.get("status", "not_run")),
        security_status="passed" if security_pass else "failed",
        quality_gate=run.quality_gate,
        feature_coverage=round(coverage, 4),
        agent_calls=run.agent_calls,
        revision_count=run.revision_count,
        first_pass_passed=first_pass["passed"],
        first_pass_score=first_pass["score"],
        first_pass_browser_status=first_pass["browser_status"],
        duration_seconds=round(max(0, (run.updated_at - run.created_at).total_seconds()), 2),
        started_at=run.created_at,
        completed_at=run.updated_at,
    )


def aggregate_metrics(results: list[EvaluationCaseResult]) -> EvaluationMetrics:
    completed = [item for item in results if item.status in {"passed", "failed", "cancelled"}]
    total = len(results)
    count = len(completed)
    passed = [item for item in completed if item.passed]
    first_passed = [item for item in completed if item.first_pass_passed]
    failures = Counter(
        item.failure_category for item in completed if item.failure_category != "none"
    )

    def ratio(predicate) -> float:
        return round(sum(1 for item in completed if predicate(item)) / count, 4) if count else 0

    def average(selector) -> float:
        return round(sum(selector(item) for item in completed) / count, 2) if count else 0

    def cohort_metrics(cohort: list[EvaluationCaseResult]) -> ComplexityMetrics:
        cohort_completed = [
            item for item in cohort if item.status in {"passed", "failed", "cancelled"}
        ]
        cohort_count = len(cohort_completed)

        def cohort_ratio(predicate) -> float:
            return (
                round(
                    sum(1 for item in cohort_completed if predicate(item)) / cohort_count,
                    4,
                )
                if cohort_count
                else 0
            )

        return ComplexityMetrics(
            total_cases=len(cohort),
            completed_cases=cohort_count,
            passed_cases=sum(1 for item in cohort_completed if item.passed),
            success_rate=cohort_ratio(lambda item: item.passed),
            first_pass_success_rate=cohort_ratio(lambda item: item.first_pass_passed),
            average_score=(
                round(sum(item.score for item in cohort_completed) / cohort_count, 2)
                if cohort_count
                else 0
            ),
            browser_pass_rate=cohort_ratio(lambda item: item.browser_status == "passed"),
            feature_coverage_rate=(
                round(
                    sum(item.feature_coverage for item in cohort_completed) / cohort_count,
                    4,
                )
                if cohort_count
                else 0
            ),
            revision_rate=cohort_ratio(lambda item: item.revision_count > 0),
        )

    complexity_breakdown = {
        complexity: cohort_metrics(
            [item for item in results if item.complexity == complexity]
        )
        for complexity in ("simple", "complex")
        if any(item.complexity == complexity for item in results)
    }

    return EvaluationMetrics(
        total_cases=total,
        completed_cases=count,
        passed_cases=len(passed),
        first_pass_passed_cases=len(first_passed),
        success_rate=ratio(lambda item: item.passed),
        first_pass_success_rate=ratio(lambda item: item.first_pass_passed),
        average_score=average(lambda item: item.score),
        first_pass_average_score=average(lambda item: item.first_pass_score),
        browser_pass_rate=ratio(lambda item: item.browser_status == "passed"),
        feature_coverage_rate=round(
            sum(item.feature_coverage for item in completed) / count, 4
        )
        if count
        else 0,
        artifact_pass_rate=ratio(lambda item: item.artifact_status == "passed"),
        fallback_rate=ratio(lambda item: item.source_mode == "controlled_template_fallback"),
        revision_rate=ratio(lambda item: item.revision_count > 0),
        average_agent_calls=average(lambda item: item.agent_calls),
        average_duration_seconds=average(lambda item: item.duration_seconds),
        failure_categories=dict(sorted(failures.items())),
        complexity_breakdown=complexity_breakdown,
    )


def acceptance_gates(evaluation: EvaluationRun) -> list[AcceptanceGate]:
    metrics = evaluation.metrics
    thresholds = evaluation.request.thresholds
    definitions = (
        ("任务成功率", metrics.success_rate, ">=", thresholds.min_success_rate),
        ("平均质量分", metrics.average_score, ">=", thresholds.min_average_score),
        ("浏览器通过率", metrics.browser_pass_rate, ">=", thresholds.min_browser_pass_rate),
        ("功能覆盖率", metrics.feature_coverage_rate, ">=", thresholds.min_feature_coverage_rate),
        ("平均模型调用数", metrics.average_agent_calls, "<=", thresholds.max_average_agent_calls),
    )
    return [
        AcceptanceGate(
            name=name,
            actual=actual,
            operator=operator,
            threshold=threshold,
            passed=actual >= threshold if operator == ">=" else actual <= threshold,
        )
        for name, actual, operator, threshold in definitions
    ]


def _comparison(current: EvaluationRun, baseline: EvaluationRun | None) -> dict[str, float | str | None]:
    if not baseline:
        return {"baseline_id": None}
    return {
        "baseline_id": baseline.id,
        "success_rate_delta": round(current.metrics.success_rate - baseline.metrics.success_rate, 4),
        "first_pass_success_rate_delta": round(
            current.metrics.first_pass_success_rate - baseline.metrics.first_pass_success_rate,
            4,
        ),
        "average_score_delta": round(current.metrics.average_score - baseline.metrics.average_score, 2),
        "first_pass_average_score_delta": round(
            current.metrics.first_pass_average_score - baseline.metrics.first_pass_average_score,
            2,
        ),
        "browser_pass_rate_delta": round(
            current.metrics.browser_pass_rate - baseline.metrics.browser_pass_rate, 4
        ),
        "feature_coverage_rate_delta": round(
            current.metrics.feature_coverage_rate - baseline.metrics.feature_coverage_rate, 4
        ),
        "average_agent_calls_delta": round(
            current.metrics.average_agent_calls - baseline.metrics.average_agent_calls, 2
        ),
        "average_duration_seconds_delta": round(
            current.metrics.average_duration_seconds - baseline.metrics.average_duration_seconds, 2
        ),
    }


def _skill_promotion_decision(
    current: EvaluationRun, baseline: EvaluationRun | None
) -> dict[str, bool | float | str | list[str]]:
    if current.request.skill_profile != "candidate":
        return {"applicable": False, "eligible": False, "reason": "not_candidate_profile"}
    if baseline is None:
        return {"applicable": True, "eligible": False, "reason": "missing_baseline"}
    reasons: list[str] = []
    if baseline.request.skill_profile != "baseline":
        reasons.append("baseline_profile_must_be_baseline")
    if baseline.case_ids != current.case_ids:
        reasons.append("case_ids_do_not_match")
    if baseline.request.provider != current.request.provider:
        reasons.append("provider_does_not_match")
    if not baseline.request.first_pass_only or not current.request.first_pass_only:
        reasons.append("first_pass_only_required")
    success_delta = round(
        current.metrics.first_pass_success_rate - baseline.metrics.first_pass_success_rate,
        4,
    )
    score_delta = round(
        current.metrics.first_pass_average_score - baseline.metrics.first_pass_average_score,
        2,
    )
    browser_delta = round(
        current.metrics.browser_pass_rate - baseline.metrics.browser_pass_rate, 4
    )
    coverage_delta = round(
        current.metrics.feature_coverage_rate - baseline.metrics.feature_coverage_rate, 4
    )
    calls_delta = round(
        current.metrics.average_agent_calls - baseline.metrics.average_agent_calls, 2
    )
    demonstrated_improvement = success_delta > 0 or (
        success_delta == 0 and score_delta >= 2
    )
    if not demonstrated_improvement:
        reasons.append("no_first_pass_improvement")
    if success_delta < 0:
        reasons.append("first_pass_success_regressed")
    if browser_delta < 0:
        reasons.append("browser_pass_rate_regressed")
    if coverage_delta < 0:
        reasons.append("feature_coverage_regressed")
    if calls_delta > 0:
        reasons.append("agent_calls_increased")
    return {
        "applicable": True,
        "eligible": not reasons,
        "reason": "passed" if not reasons else "rejected",
        "reasons": reasons,
        "first_pass_success_rate_delta": success_delta,
        "first_pass_average_score_delta": score_delta,
        "browser_pass_rate_delta": browser_delta,
        "feature_coverage_rate_delta": coverage_delta,
        "average_agent_calls_delta": calls_delta,
    }


def _report(evaluation: EvaluationRun) -> str:
    metrics = evaluation.metrics
    failed = [item for item in evaluation.results if not item.passed]
    comparison = evaluation.comparison
    lines = [
        f"# DemoPilot 自动评测报告 · {evaluation.request.version_label}",
        "",
        f"- 评测 ID：`{evaluation.id}`",
        f"- Provider：`{evaluation.request.provider}`",
        f"- 版本：`{__version__}`",
        f"- Skill Profile：`{evaluation.request.skill_profile}`",
        f"- 需求范围：`{evaluation.request.complexity}`",
        f"- 结论：`{evaluation.verdict}`",
        f"- 用例：{metrics.passed_cases}/{metrics.total_cases} 通过",
        f"- 成功率：{metrics.success_rate:.1%}",
        f"- 首轮成功率：{metrics.first_pass_success_rate:.1%}",
        f"- 平均分：{metrics.average_score:.1f}",
        f"- 首轮平均分：{metrics.first_pass_average_score:.1f}",
        f"- 浏览器通过率：{metrics.browser_pass_rate:.1%}",
        f"- 功能覆盖率：{metrics.feature_coverage_rate:.1%}",
        f"- 平均调用：{metrics.average_agent_calls:.2f}",
        f"- 平均耗时：{metrics.average_duration_seconds:.2f}s",
        "",
        "## 验收门",
        "",
        *[
            f"- {'PASS' if gate.passed else 'FAIL'} · {gate.name}：{gate.actual} {gate.operator} {gate.threshold}"
            for gate in evaluation.gates
        ],
    ]
    if metrics.complexity_breakdown:
        lines.extend(["", "## 难度分组", ""])
        for complexity, group in metrics.complexity_breakdown.items():
            label = "简单要求" if complexity == "simple" else "复杂要求"
            lines.append(
                f"- {label}：{group.passed_cases}/{group.total_cases} 通过 · "
                f"成功率 {group.success_rate:.1%} · 平均分 {group.average_score:.1f} · "
                f"返工率 {group.revision_rate:.1%}"
            )
    lines.extend(["", "## 失败与未解决项", ""])
    if failed:
        for item in failed:
            detail = "；".join(item.issues[:3]) or "未提供具体错误"
            lines.append(f"- `{item.case_id}` {item.case_name} · {item.failure_category} · {detail}")
    else:
        lines.append(
            "- 无阻断失败。纯展示型 Demo 使用本地虚构数据，不接生产系统属于既定完成范围。"
        )
    lines.extend(["", "## 版本对比", ""])
    if comparison.get("baseline_id"):
        lines.extend(f"- {key}: {value}" for key, value in comparison.items())
    else:
        lines.append("- 首次评测，无同 Provider 基线。")
    if evaluation.skill_promotion.get("applicable"):
        lines.extend(
            [
                "",
                "## Skill 晋级门",
                "",
                f"- eligible: {evaluation.skill_promotion.get('eligible')}",
                f"- reason: {evaluation.skill_promotion.get('reason')}",
                f"- reasons: {evaluation.skill_promotion.get('reasons', [])}",
            ]
        )
    lines.extend(["", "## 逐用例证据", ""])
    for item in evaluation.results:
        lines.append(
            f"- `{item.case_id}` → run `{item.run_id}` · score={item.score} · "
            f"browser={item.browser_status} · source={item.source_mode}"
        )
    return "\n".join(lines) + "\n"


class EvaluationManager:
    def __init__(
        self,
        evaluation_store: EvaluationStore,
        run_store: RunStore,
        run_manager: RunManager,
    ) -> None:
        self.store = evaluation_store
        self.run_store = run_store
        self.run_manager = run_manager
        self.cases = {item.id: item for item in builtin_evaluation_cases()}
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def schedule(self, evaluation_id: str) -> None:
        existing = self.tasks.get(evaluation_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self.execute(evaluation_id))
        self.tasks[evaluation_id] = task
        task.add_done_callback(
            lambda _task, identifier=evaluation_id: self.tasks.pop(identifier, None)
        )

    def recover(self) -> list[str]:
        recovered: list[str] = []
        for evaluation in self.store.list():
            if evaluation.status not in {"queued", "running"}:
                continue
            evaluation.status = "queued"
            evaluation.active_run_ids = []
            for result in evaluation.results:
                if result.status == "running":
                    result.status = "pending"
            self.store.save(evaluation)
            self.schedule(evaluation.id)
            recovered.append(evaluation.id)
        return recovered

    async def _run_case(
        self,
        evaluation: EvaluationRun,
        result: EvaluationCaseResult,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            latest = self.store.get(evaluation.id)
            if not latest or latest.cancel_requested:
                result.status = "cancelled"
                result.failure_category = "cancelled"
                return
            case = self.cases[result.case_id]
            result.status = "running"
            result.started_at = utc_now()
            run = self.run_store.get(result.run_id) if result.run_id else None
            if run is None:
                request_payload = DemoRequest(
                    client_name=f"评测客户·{case.id}",
                    project_name=case.name,
                    industry=case.industry,
                    scenario=case.scenario,
                    audience=case.audience,
                    must_haves=case.must_haves,
                    brand_tone=case.brand_tone,
                    primary_color=case.primary_color,
                    provider=evaluation.request.provider,
                    require_execution_approval=False,
                )
                run = DemoRun(id=uuid.uuid4().hex[:12], request=request_payload)
                skill_runtime = self.run_manager.orchestrator.skill_registry.describe_profile(
                    evaluation.request.skill_profile
                )
                run.outputs["skill_runtime"] = skill_runtime
                run.outputs["evaluation_trace"] = {
                    "evaluation_id": evaluation.id,
                    "case_id": case.id,
                    "version_label": evaluation.request.version_label,
                    "skill_profile": evaluation.request.skill_profile,
                    "skill_bundle_sha256": skill_runtime["bundle_sha256"],
                    "first_pass_only": evaluation.request.first_pass_only,
                    "builder_preflight_enabled": (
                        evaluation.request.builder_preflight_enabled
                    ),
                    "input_sha256": hashlib.sha256(
                        json.dumps(case.model_dump(), ensure_ascii=False, sort_keys=True).encode()
                    ).hexdigest(),
                }
                self.run_store.create(run)
                result.run_id = run.id
            if run.status not in TERMINAL_STATUSES:
                evaluation.active_run_ids.append(run.id)
                self.run_manager.schedule(run.id)
            self.store.save(evaluation)
            while True:
                await asyncio.sleep(0.25)
                current_evaluation = self.store.get(evaluation.id)
                if current_evaluation and current_evaluation.cancel_requested:
                    active_run = self.run_store.get(run.id)
                    if active_run:
                        self.run_manager.cancel(active_run)
                current = self.run_store.get(run.id)
                if current and current.status in TERMINAL_STATUSES:
                    break
            evaluated = evaluate_demo_run(case, current)
            index = evaluation.results.index(result)
            evaluation.results[index] = evaluated
            if run.id in evaluation.active_run_ids:
                evaluation.active_run_ids.remove(run.id)
            evaluation.metrics = aggregate_metrics(evaluation.results)
            evaluation.progress = round(
                100 * evaluation.metrics.completed_cases / len(evaluation.results)
            )
            self.store.save(evaluation)

    async def execute(self, evaluation_id: str) -> None:
        evaluation = self.store.get(evaluation_id)
        if not evaluation:
            return
        evaluation.status = "running"
        evaluation.error = None
        self.store.save(evaluation)
        started = time.perf_counter()
        try:
            semaphore = asyncio.Semaphore(evaluation.request.concurrency)
            await asyncio.gather(
                *(
                    self._run_case(evaluation, result, semaphore)
                    for result in evaluation.results
                    if result.status == "pending"
                )
            )
            latest = self.store.get(evaluation.id)
            if latest and latest.cancel_requested:
                evaluation.status = "cancelled"
                evaluation.verdict = "failed"
            else:
                evaluation.metrics = aggregate_metrics(evaluation.results)
                evaluation.gates = acceptance_gates(evaluation)
                evaluation.verdict = (
                    "passed" if all(gate.passed for gate in evaluation.gates) else "failed"
                )
                evaluation.status = "completed"
                evaluation.progress = 100
            baseline = (
                self.store.get(evaluation.request.baseline_id)
                if evaluation.request.baseline_id
                else self.store.latest_baseline(
                    evaluation.request.provider,
                    evaluation.request.complexity,
                    exclude_id=evaluation.id,
                )
            )
            evaluation.comparison = _comparison(evaluation, baseline)
            evaluation.skill_promotion = _skill_promotion_decision(evaluation, baseline)
            evaluation.active_run_ids = []
            evaluation.report_url = f"/api/evaluations/{evaluation.id}/report"
            self.store.save_report(evaluation, _report(evaluation))
            self.store.save(evaluation)
        except Exception as exc:
            evaluation.status = "failed"
            evaluation.verdict = "failed"
            evaluation.active_run_ids = []
            evaluation.error = str(exc)[:500]
            self.store.save(evaluation)
        finally:
            _ = time.perf_counter() - started

    def cancel(self, evaluation: EvaluationRun) -> EvaluationRun:
        if evaluation.status in {"completed", "failed", "cancelled"}:
            return evaluation
        evaluation.cancel_requested = True
        evaluation.status = "cancelled"
        evaluation.verdict = "failed"
        self.store.save(evaluation)
        for run_id in evaluation.active_run_ids:
            run = self.run_store.get(run_id)
            if run:
                self.run_manager.cancel(run)
        task = self.tasks.get(evaluation.id)
        if task and not task.done():
            task.cancel()
        return evaluation

    async def shutdown(self) -> None:
        tasks = [task for task in self.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
