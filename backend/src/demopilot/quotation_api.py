"""Read-only local delivery API; DB-committed current revision is authoritative."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .quotation_release import ReleaseRegistry, ReleaseRejected


def create_app(registry_root):
    registry = ReleaseRegistry(registry_root)
    app = FastAPI(title="DemoPilot Verified Quotation v2")

    @app.get("/api/projects")
    def projects():
        snapshot = registry.snapshot()
        # Lease tokens never leave the server.
        return dict(
            intents=snapshot["intents"],
            releases=snapshot["releases"],
            jobs=[{k: v for k, v in j.items() if k != "token"} for j in snapshot["jobs"]],
        )

    @app.get("/", response_class=HTMLResponse)
    def index():
        import html

        snapshot = registry.snapshot()
        rows = []
        for intent in snapshot["intents"]:
            pid = intent["project"]
            release = registry.resolve(pid)
            link = (
                f'<a href="/projects/{html.escape(pid, quote=True)}/demo/index.html">打开已验收报价应用</a>'
                if release
                else "隐藏：当前需求尚无通过业务验收的结果"
            )
            rows.append(
                f"<tr><td>{html.escape(pid)}</td><td>v{intent['revision']}</td><td>{link}</td></tr>"
            )
        return (
            '<!doctype html><meta charset="utf-8"><title>DemoPilot 业务验收发布台</title><style>body{font:16px system-ui;max-width:1000px;margin:60px auto;color:#172d45}td,th{padding:18px;border-bottom:1px solid #ddd}a{color:#176bc8}</style><h1>报价应用 · 验收发布台</h1><p>只有当前需求版本且通过业务验收的产物可以打开。</p><table><tr><th>应用</th><th>需求版本</th><th>发布状态</th></tr>'
            + "".join(rows)
            + "</table>"
        )

    @app.get("/projects/{project}/demo/{file_path:path}")
    def artifact(project: str, file_path: str):
        try:
            release = registry.resolve(project)
        except ReleaseRejected as exc:
            raise HTTPException(409, str(exc)) from exc
        if not release:
            raise HTTPException(404, "No accepted release for the current intent revision")
        from urllib.parse import quote

        # Relative CSS/JS requests now carry exactly the same accepted hash as
        # their HTML document, even if another revision publishes meanwhile.
        return RedirectResponse(
            f"/accepted/{quote(project, safe='')}/{release['revision']}/{release['artifact']}/{quote(file_path, safe='/')}",
            status_code=307,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/accepted/{project}/{revision}/{digest}/{file_path:path}")
    def accepted_artifact(project: str, revision: int, digest: str, file_path: str):
        try:
            release = registry.resolve_accepted_bundle(project, revision, digest)
        except ReleaseRejected as exc:
            raise HTTPException(409, str(exc)) from exc
        if not release:
            raise HTTPException(404, "No accepted bundle at this revision and hash")
        root = Path(release["path"]).resolve()
        target = (root / file_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "Artifact path unavailable")
        return FileResponse(
            target,
            headers={
                "Cache-Control": "no-store",
                "X-DemoPilot-Revision": str(revision),
                "X-DemoPilot-Artifact": digest,
            },
        )

    return app
