from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import __version__
from .config import Settings
from .evaluation_cases import builtin_evaluation_cases
from .evaluation_models import EvaluationCase, EvaluationRequest, EvaluationRun
from .evaluation_store import EvaluationStore
from .evaluator import EvaluationManager
from .models import ApprovalDecision, DemoRequest, DemoRun, HealthResponse, RunStatus
from .orchestrator import DemoOrchestrator
from .providers import (
    AgentProvider,
    ClaudeAgentProvider,
    MockAgentProvider,
    OpenAICompatibleAgentProvider,
)
from .runtime import RunManager
from .storage import RunStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = RunStore(settings.data_dir)
    providers: dict[str, AgentProvider] = {
        "mock": MockAgentProvider(),
        "claude": ClaudeAgentProvider(),
    }
    for provider_settings in settings.compatible_providers():
        if provider_settings.enabled:
            providers[provider_settings.name] = OpenAICompatibleAgentProvider(
                name=provider_settings.name,
                api_key=provider_settings.api_key,
                base_url=provider_settings.base_url,
                model=provider_settings.model,
            )
    orchestrator = DemoOrchestrator(
        store,
        providers,
        max_agent_calls=settings.max_agent_calls,
        max_revision_rounds=settings.max_revision_rounds,
        max_parallel_agents=settings.max_parallel_agents,
    )
    manager = RunManager(store, orchestrator)
    evaluation_store = EvaluationStore(settings.data_dir)
    evaluation_manager = EvaluationManager(evaluation_store, store, manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.recover()
        evaluation_manager.recover()
        yield
        await evaluation_manager.shutdown()
        await manager.shutdown()

    app = FastAPI(
        title="DemoPilot API",
        version=__version__,
        description="Turn a sales brief into a controlled, reviewable customer demo package.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.settings = settings
    app.state.store = store
    app.state.run_manager = manager
    app.state.evaluation_store = evaluation_store
    app.state.evaluation_manager = evaluation_manager

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        availability = {
            "mock": True,
            "claude": settings.enable_claude,
            **{
                item.name: item.enabled
                for item in settings.compatible_providers()
            },
        }
        return HealthResponse(
            version=__version__,
            claude_enabled=settings.enable_claude,
            providers=availability,
        )

    @app.get("/api/templates")
    async def templates() -> list[dict[str, object]]:
        return [
            {
                "id": "operations",
                "name": "智能运营台",
                "industry": "企业服务",
                "scenario": "日常任务分散在多个系统，团队难以及时识别优先级并追踪结果。",
                "must_haves": ["运营总览", "智能任务分派", "效果追踪"],
            },
            {
                "id": "sales",
                "name": "销售作战室",
                "industry": "B2B 销售",
                "scenario": "客户信息与跟进动作不连贯，销售需要快速定位高价值机会。",
                "must_haves": ["客户全景", "机会评分", "跟进建议"],
            },
            {
                "id": "support",
                "name": "服务质量中心",
                "industry": "客户服务",
                "scenario": "服务问题响应慢、复盘难，管理者缺少可解释的质量视图。",
                "must_haves": ["工单总览", "风险预警", "质量复盘"],
            },
        ]

    @app.get("/api/evaluation-cases", response_model=list[EvaluationCase])
    async def evaluation_cases() -> list[EvaluationCase]:
        return builtin_evaluation_cases()

    @app.post("/api/evaluations", response_model=EvaluationRun, status_code=202)
    async def create_evaluation(payload: EvaluationRequest) -> EvaluationRun:
        if payload.provider == "claude" and not settings.enable_claude:
            raise HTTPException(status_code=400, detail="Claude provider is disabled")
        if payload.provider not in providers:
            raise HTTPException(
                status_code=400,
                detail=f"{payload.provider} provider is not configured",
            )
        all_cases = builtin_evaluation_cases()
        case_map = {item.id: item for item in all_cases}
        selected_ids = list(dict.fromkeys(payload.case_ids)) if payload.case_ids else [
            item.id for item in all_cases[: payload.case_limit]
        ]
        unknown = [case_id for case_id in selected_ids if case_id not in case_map]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail="Unknown evaluation cases: " + ", ".join(unknown),
            )
        if len(selected_ids) > payload.case_limit:
            selected_ids = selected_ids[: payload.case_limit]
        if payload.provider != "mock" and len(selected_ids) > 3:
            raise HTTPException(
                status_code=400,
                detail="Real provider evaluations are limited to 3 cases",
            )
        evaluation = EvaluationRun(
            id=uuid.uuid4().hex[:12],
            request=payload,
            case_ids=selected_ids,
            results=[
                {
                    "case_id": case_id,
                    "case_name": case_map[case_id].name,
                }
                for case_id in selected_ids
            ],
        )
        evaluation.metrics.total_cases = len(selected_ids)
        evaluation_store.create(evaluation)
        evaluation_manager.schedule(evaluation.id)
        return evaluation

    @app.get("/api/evaluations", response_model=list[EvaluationRun])
    async def list_evaluations() -> list[EvaluationRun]:
        return evaluation_store.list()

    @app.get("/api/evaluations/{evaluation_id}", response_model=EvaluationRun)
    async def get_evaluation(evaluation_id: str) -> EvaluationRun:
        evaluation = evaluation_store.get(evaluation_id)
        if not evaluation:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return evaluation

    @app.get("/api/evaluations/{evaluation_id}/events")
    async def stream_evaluation(evaluation_id: str) -> StreamingResponse:
        if not evaluation_store.get(evaluation_id):
            raise HTTPException(status_code=404, detail="Evaluation not found")

        async def event_stream():
            last_version = ""
            heartbeat = 0
            while True:
                evaluation = evaluation_store.get(evaluation_id)
                if not evaluation:
                    return
                version = evaluation.updated_at.isoformat()
                if version != last_version:
                    last_version = version
                    yield (
                        f"id: {version}\nevent: evaluation\n"
                        f"data: {evaluation.model_dump_json()}\n\n"
                    )
                    heartbeat = 0
                    if evaluation.status in {"completed", "failed", "cancelled"}:
                        return
                else:
                    heartbeat += 1
                    if heartbeat >= 30:
                        yield ": heartbeat\n\n"
                        heartbeat = 0
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/evaluations/{evaluation_id}/cancel", response_model=EvaluationRun)
    async def cancel_evaluation(evaluation_id: str) -> EvaluationRun:
        evaluation = evaluation_store.get(evaluation_id)
        if not evaluation:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return evaluation_manager.cancel(evaluation)

    @app.get("/api/evaluations/{evaluation_id}/report")
    async def evaluation_report(evaluation_id: str) -> FileResponse:
        if not evaluation_store.get(evaluation_id):
            raise HTTPException(status_code=404, detail="Evaluation not found")
        path = evaluation_store.report_path(evaluation_id)
        if not path:
            raise HTTPException(status_code=404, detail="Evaluation report not ready")
        return FileResponse(
            path=path,
            media_type="text/markdown",
            filename=f"demopilot-evaluation-{evaluation_id}.md",
        )

    @app.post("/api/runs", response_model=DemoRun, status_code=202)
    async def create_run(payload: DemoRequest) -> DemoRun:
        if payload.provider == "claude" and not settings.enable_claude:
            raise HTTPException(
                status_code=400,
                detail="Claude provider is disabled. Set DEMOPILOT_ENABLE_CLAUDE=true after setup.",
            )
        if payload.provider not in providers:
            raise HTTPException(
                status_code=400,
                detail=f"{payload.provider} provider is not configured in the project environment.",
            )
        run = DemoRun(id=uuid.uuid4().hex[:12], request=payload)
        run.outputs["skill_runtime"] = orchestrator.skill_registry.describe_profile(
            "approved"
        )
        store.create(run)
        manager.schedule(run.id)
        return run

    @app.get("/api/runs", response_model=list[DemoRun])
    async def list_runs() -> list[DemoRun]:
        return store.list()

    @app.get("/api/runs/{run_id}", response_model=DemoRun)
    async def get_run(run_id: str) -> DemoRun:
        run = store.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.get("/api/runs/{run_id}/events")
    async def stream_run(run_id: str) -> StreamingResponse:
        if not store.get(run_id):
            raise HTTPException(status_code=404, detail="Run not found")

        async def event_stream():
            last_version = ""
            heartbeat = 0
            while True:
                run = store.get(run_id)
                if not run:
                    return
                version = run.updated_at.isoformat()
                if version != last_version:
                    last_version = version
                    yield f"id: {version}\nevent: run\ndata: {run.model_dump_json()}\n\n"
                    heartbeat = 0
                    if run.status in {
                        RunStatus.COMPLETED,
                        RunStatus.FAILED,
                        RunStatus.CANCELLED,
                    }:
                        return
                else:
                    heartbeat += 1
                    if heartbeat >= 30:
                        yield ": heartbeat\n\n"
                        heartbeat = 0
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/runs/{run_id}/approvals/{approval_id}", response_model=DemoRun)
    async def decide_approval(
        run_id: str, approval_id: str, decision: ApprovalDecision
    ) -> DemoRun:
        run = store.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        approval = next((item for item in run.approvals if item.id == approval_id), None)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        if approval.status != "pending":
            raise HTTPException(status_code=409, detail="Approval already resolved")
        approval.status = "approved" if decision.decision == "approve" else "declined"
        approval.resolved_at = datetime.now(UTC)
        if decision.decision == "approve":
            run.status = RunStatus.QUEUED
            run.cancel_requested = False
            run.checkpoint = f"approval:{approval.action}:approved"
            store.save(run)
            manager.schedule(run.id)
        else:
            store.save(run)
            manager.cancel(run)
        return store.get(run.id) or run

    @app.post("/api/runs/{run_id}/cancel", response_model=DemoRun)
    async def cancel_run(run_id: str) -> DemoRun:
        run = store.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return manager.cancel(run)

    @app.post("/api/runs/{run_id}/resume", response_model=DemoRun, status_code=202)
    async def resume_run(run_id: str) -> DemoRun:
        run = store.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status not in {RunStatus.FAILED, RunStatus.CANCELLED}:
            raise HTTPException(status_code=409, detail="Only failed or cancelled runs can resume")
        return manager.resume(run)

    @app.get("/api/runs/{run_id}/files/{file_path:path}")
    async def get_file(run_id: str, file_path: str) -> FileResponse:
        run = store.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        base_dir = store.run_dir(run_id).resolve()
        requested = (base_dir / file_path).resolve()
        try:
            requested.relative_to(base_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid file path") from exc
        allowed_paths = {(base_dir / item.relative_path).resolve() for item in run.artifacts}
        demo_assets = (base_dir / "artifacts" / "demo").resolve()
        is_demo_asset = demo_assets in requested.parents and requested.name in {
            "index.html",
            "styles.css",
            "app.js",
        }
        if requested not in allowed_paths and not is_demo_asset:
            raise HTTPException(status_code=404, detail="Artifact not found")
        if not requested.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")
        media_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".md": "text/markdown",
            ".zip": "application/zip",
            ".png": "image/png",
        }
        return FileResponse(
            path=Path(requested),
            media_type=media_types.get(requested.suffix.lower(), "application/octet-stream"),
            filename=None if requested.suffix.lower() in {".html", ".css", ".js"} else requested.name,
        )

    return app


app = create_app()
