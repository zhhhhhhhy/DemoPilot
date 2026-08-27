from __future__ import annotations

import asyncio

from .models import DemoRun, RunStatus
from .orchestrator import DemoOrchestrator
from .storage import RunStore

TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


class RunManager:
    """Owns in-process run tasks while durable state stays in RunStore."""

    def __init__(self, store: RunStore, orchestrator: DemoOrchestrator) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def schedule(self, run_id: str) -> None:
        existing = self.tasks.get(run_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self.orchestrator.execute(run_id))
        self.tasks[run_id] = task
        task.add_done_callback(lambda _task, identifier=run_id: self.tasks.pop(identifier, None))

    def recover(self) -> list[str]:
        recovered: list[str] = []
        for run in self.store.list():
            if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                continue
            if run.status == RunStatus.RUNNING:
                run.status = RunStatus.QUEUED
                run.resume_count += 1
                run.error = None
                self.store.save(run)
            self.schedule(run.id)
            recovered.append(run.id)
        return recovered

    def cancel(self, run: DemoRun) -> DemoRun:
        if run.status in TERMINAL_STATUSES:
            return run
        run.cancel_requested = True
        run.status = RunStatus.CANCELLED
        run.current_agent = None
        run.checkpoint = "cancelled"
        run.error = "任务已由用户取消"
        self.store.save(run)
        task = self.tasks.get(run.id)
        if task and not task.done():
            task.cancel()
        return run

    def resume(self, run: DemoRun) -> DemoRun:
        if run.status not in {RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        quality_gate_failed = run.quality_gate == "failed"
        run.status = RunStatus.QUEUED
        run.cancel_requested = False
        run.error = None
        run.quality_gate = "pending"
        run.resume_count += 1
        run.checkpoint = f"resume:{run.checkpoint or 'start'}"
        if quality_gate_failed:
            iteration = run.revision_count
            validation_key = f"artifact_validation_iteration_{iteration}"
            reviewer_key = f"reviewer_iteration_{iteration}"
            checkpoint = run.checkpoint
            while checkpoint.startswith("resume:"):
                checkpoint = checkpoint.removeprefix("resume:")
            completed_review = (
                checkpoint.startswith("agent:reviewer:iteration:")
                and validation_key in run.outputs
                and reviewer_key in run.outputs
            )
            completed_validation = (
                checkpoint.startswith("artifacts:iteration:")
                and validation_key in run.outputs
            )
            if not completed_validation and not completed_review:
                run.outputs.pop("artifact_validation", None)
                run.outputs.pop(validation_key, None)
            if not completed_review:
                for key in (
                    "reviewer",
                    reviewer_key,
                    "qa",
                    f"qa_iteration_{iteration}",
                ):
                    run.outputs.pop(key, None)
        self.store.save(run)
        self.schedule(run.id)
        return run

    async def shutdown(self) -> None:
        tasks = [task for task in self.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
