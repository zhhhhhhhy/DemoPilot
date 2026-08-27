from __future__ import annotations

import hashlib
import re
import time
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path

from .models import DemoRun, ToolReceipt


class SandboxViolation(RuntimeError):
    """Raised when generated content crosses the local demo sandbox boundary."""


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{12,}"),
)
_UNSAFE_WEB_PATTERNS = (
    (re.compile(r"(?i)\b(?:fetch|XMLHttpRequest|WebSocket)\s*\("), "外部网络调用"),
    (re.compile(r"(?i)<\s*(?:iframe|object|embed)\b"), "外部嵌入内容"),
    (re.compile(r"(?i)javascript\s*:"), "javascript URL"),
    (re.compile(r"(?i)\b(?:document\.cookie|window\.open)\b"), "浏览器敏感能力"),
    (re.compile(r"(?i)(?:src|href)\s*=\s*['\"]https?://"), "远程页面资源"),
    (re.compile(r"(?i)<script(?![^>]*\bsrc\s*=)[^>]*>"), "HTML 内联脚本"),
    (re.compile(r"(?i)\son[a-z]+\s*="), "HTML 内联事件处理器"),
    (re.compile(r"(?i)(?:\beval\s*\(|\bnew\s+Function\s*\()"), "动态代码执行"),
)
_INNER_HTML_ASSIGNMENT = re.compile(r"(?i)\.innerHTML\s*=\s*([^;\r\n]*)")
_ALLOWED_SUFFIXES = {".html", ".css", ".js", ".json", ".md", ".zip", ".png"}


def scan_generated_text(relative: str, content: str) -> list[str]:
    """Return deterministic safety findings without writing generated content."""

    findings: list[str] = []
    for pattern in _SECRET_PATTERNS:
        if pattern.search(content):
            findings.append("疑似密钥或凭证")
            break
    if Path(relative).suffix.lower() in {".html", ".css", ".js"}:
        for pattern, label in _UNSAFE_WEB_PATTERNS:
            if pattern.search(content):
                findings.append(label)
        for match in _INNER_HTML_ASSIGNMENT.finditer(content):
            # Clearing an existing node cannot inject markup. Any non-empty
            # assignment remains blocked; generated content should otherwise
            # use textContent/createElement/replaceChildren.
            if match.group(1).strip() not in {"''", '""', "``"}:
                findings.append("不安全 HTML 注入")
                break
    return findings


class SandboxWorkspace:
    """Run-scoped file tools with path containment, hooks, hashes and receipts."""

    def __init__(
        self,
        run: DemoRun,
        run_dir: Path,
        on_change: Callable[[DemoRun], object] | None = None,
        *,
        max_text_bytes: int = 1_000_000,
    ) -> None:
        self.run = run
        self.root = run_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.on_change = on_change
        self.max_text_bytes = max_text_bytes

    def _persist(self) -> None:
        if self.on_change:
            self.on_change(self.run)

    def _resolve(self, relative_path: str) -> tuple[str, Path]:
        normalized = Path(relative_path.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise SandboxViolation("工具路径必须位于当前任务沙箱内")
        relative = normalized.as_posix().lstrip("./")
        if not relative or not (
            relative.startswith("artifacts/")
            or relative == f"{self.run.id}-demo-package.zip"
        ):
            raise SandboxViolation("工具只能写入 artifacts/ 或当前任务交付包")
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise SandboxViolation("工具路径逃逸了当前任务沙箱") from exc
        if target.suffix.lower() not in _ALLOWED_SUFFIXES:
            raise SandboxViolation(f"不允许生成 {target.suffix or '无扩展名'} 文件")
        return relative, target

    @staticmethod
    def _scan_text(relative: str, content: str) -> list[str]:
        return scan_generated_text(relative, content)

    def _receipt(
        self,
        *,
        tool_name: str,
        action: str,
        status: str,
        input_summary: str,
        output_summary: str,
        relative_paths: list[str] | None = None,
        sha256: dict[str, str] | None = None,
        started: float,
    ) -> ToolReceipt:
        receipt = ToolReceipt(
            id=uuid.uuid4().hex,
            tool_name=tool_name,
            action=action,
            agent_id="runner",
            status=status,
            input_summary=input_summary[:240],
            output_summary=output_summary[:500],
            relative_paths=relative_paths or [],
            sha256=sha256 or {},
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        )
        self.run.tool_receipts.append(receipt)
        self._persist()
        return receipt

    def write_text(self, relative_path: str, content: str) -> Path:
        started = time.perf_counter()
        try:
            relative, target = self._resolve(relative_path)
            encoded = content.encode("utf-8")
            if len(encoded) > self.max_text_bytes:
                raise SandboxViolation("单个生成文件超过 1 MB 限制")
            findings = self._scan_text(relative, content)
            if findings:
                raise SandboxViolation("预写入 Hook 拒绝内容：" + "、".join(findings))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            self._receipt(
                tool_name="sandbox.write_text",
                action="write",
                status="succeeded",
                input_summary=f"写入 {relative}（{len(encoded)} bytes）",
                output_summary="预写入安全 Hook 通过；文件已落盘并完成 SHA-256 校验",
                relative_paths=[relative],
                sha256={relative: digest},
                started=started,
            )
            return target
        except Exception as exc:
            self._receipt(
                tool_name="sandbox.write_text",
                action="write",
                status="failed",
                input_summary=f"尝试写入 {relative_path}",
                output_summary=str(exc),
                started=started,
            )
            raise

    def write_bytes(self, relative_path: str, content: bytes) -> Path:
        started = time.perf_counter()
        try:
            relative, target = self._resolve(relative_path)
            if target.suffix.lower() != ".png":
                raise SandboxViolation("二进制工具目前只允许写入 PNG 证据")
            if len(content) > 5_000_000:
                raise SandboxViolation("单个截图超过 5 MB 限制")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            self._receipt(
                tool_name="sandbox.write_bytes",
                action="write",
                status="succeeded",
                input_summary=f"写入 {relative}（{len(content)} bytes）",
                output_summary="浏览器证据已落盘并完成 SHA-256 校验",
                relative_paths=[relative],
                sha256={relative: digest},
                started=started,
            )
            return target
        except Exception as exc:
            self._receipt(
                tool_name="sandbox.write_bytes",
                action="write",
                status="failed",
                input_summary=f"尝试写入二进制证据 {relative_path}",
                output_summary=str(exc),
                started=started,
            )
            raise

    def archive_directory(self, source_relative: str, archive_relative: str) -> Path:
        started = time.perf_counter()
        try:
            source_name = Path(source_relative.replace("\\", "/")).as_posix().strip("/")
            if source_name != "artifacts":
                raise SandboxViolation("只允许归档当前任务的 artifacts 目录")
            source = (self.root / source_name).resolve()
            relative, archive = self._resolve(archive_relative)
            if not source.is_dir():
                raise SandboxViolation("待归档目录不存在")
            archive.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(source.rglob("*")):
                    if path.is_file():
                        bundle.write(path, path.relative_to(source).as_posix())
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self._receipt(
                tool_name="sandbox.archive",
                action="archive",
                status="succeeded",
                input_summary="归档 artifacts/",
                output_summary=f"交付包已创建，共 {archive.stat().st_size} bytes",
                relative_paths=[relative],
                sha256={relative: digest},
                started=started,
            )
            return archive
        except Exception as exc:
            self._receipt(
                tool_name="sandbox.archive",
                action="archive",
                status="failed",
                input_summary=f"尝试归档 {source_relative}",
                output_summary=str(exc),
                started=started,
            )
            raise

    def record_validation(self, validation: dict[str, object]) -> None:
        started = time.perf_counter()
        issues = validation.get("issues")
        issue_count = len(issues) if isinstance(issues, list) else 0
        self._receipt(
            tool_name="sandbox.verify_artifacts",
            action="verify",
            status="succeeded" if issue_count == 0 else "failed",
            input_summary="检查生成文件、内容契约与交互绑定",
            output_summary=(
                "验证通过，无阻断问题"
                if issue_count == 0
                else f"验证发现 {issue_count} 个阻断问题"
            ),
            relative_paths=["artifacts"],
            started=started,
        )
