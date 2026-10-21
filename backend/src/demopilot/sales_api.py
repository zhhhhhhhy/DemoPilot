"""Sales workflow API: clarification, confirmed builds and accepted bundles."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .quotation_release import ReleaseRejected
from .sales_core import SalesCoreManager, SessionConflict


class BriefBody(BaseModel):
    brief: str = Field(min_length=3, max_length=4000)
    request_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,80}$")


class AnswerBody(BaseModel):
    answer: str = Field(min_length=1, max_length=6000)


class ConfirmBody(BaseModel):
    draft_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def sales_router(manager: SalesCoreManager):
    router = APIRouter(prefix="/api/sales-core", tags=["Sales Core"])

    def invoke(function, *args):
        try:
            return function(*args)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        except (SessionConflict, ReleaseRejected) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/sessions")
    async def sessions():
        return [manager.public(s["id"]) for s in manager.store.list()[:100]]

    @router.get("/runtime")
    async def runtime():
        return manager.runtime.snapshot()

    @router.post("/runtime/check")
    async def check_runtime():
        return await manager.runtime.recheck()

    @router.post("/sessions", status_code=202)
    async def create(body: BriefBody):
        if len(body.brief.strip()) < 3:
            raise HTTPException(422, "请写一句具体需求")
        return invoke(manager.create, body.brief.strip(), body.request_key)

    @router.get("/sessions/{identifier}")
    async def get(identifier: str):
        return invoke(manager.public, identifier)

    @router.post("/sessions/{identifier}/answers", status_code=202)
    async def answer(identifier: str, body: AnswerBody):
        if not body.answer.strip():
            raise HTTPException(422, "补充信息不能为空")
        return invoke(manager.reply, identifier, body.answer.strip())

    @router.post("/sessions/{identifier}/confirm", status_code=202)
    async def confirm(identifier: str, body: ConfirmBody):
        return invoke(manager.confirm, identifier, body.draft_hash)

    @router.post("/sessions/{identifier}/cancel")
    async def cancel(identifier: str):
        try:
            return await manager.cancel(identifier)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc

    @router.post("/sessions/{identifier}/retry", status_code=202)
    async def retry(identifier: str):
        return invoke(manager.retry, identifier)

    @router.get("/accepted/{identifier}/{revision}/{digest}/{file_path:path}")
    async def accepted(identifier: str, revision: int, digest: str, file_path: str):
        try:
            manager.store.directory(identifier)
            release = manager.registry.resolve_accepted_bundle(identifier, revision, digest)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        except ReleaseRejected as exc:
            raise HTTPException(409, str(exc)) from exc
        if not release:
            raise HTTPException(404, "该版本没有通过业务验收的产物")
        root = Path(release["path"]).resolve()
        target = (root / file_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "产物文件不存在")
        return FileResponse(target, headers={
            "Cache-Control": "no-store", "X-DemoPilot-Revision": str(revision),
            "X-DemoPilot-Artifact": digest,
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
        })

    return router
