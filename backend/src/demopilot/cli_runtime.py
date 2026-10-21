"""Shared, token-free transport checks and a fail-closed CLI circuit breaker.

An HTTP response proves reachability only. Exactly one subsequent real budgeted
CLI call must complete before a recovered circuit admits parallel calls again.
No business input, case identifier, credential or model retry is used here.
"""
from __future__ import annotations

import asyncio
import os
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class HostResumeInterrupted(RuntimeError):
    pass


class RuntimeDispatchPaused(RuntimeError):
    pass


def transport_failure(error):
    text = str(error).lower()
    return any(term in text for term in (
        "workspace routing discovery failed", "tls handshake", "connection failed",
        "error sending request", "connection refused", "failed to connect",
        "proxyconnect", "os error 10061", "rate limit", "quota exceeded",
    ))


def _local_proxy_available(value):
    try:
        parsed = urlsplit(value if "://" in value else "http://" + value)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not parsed.port:
            return None
        with socket.create_connection((parsed.hostname, parsed.port), timeout=.5):
            return True
    except (OSError, ValueError):
        return False


def _windows_proxy():
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return None
            value = winreg.QueryValueEx(key, "ProxyServer")[0]
        if "=" in value:
            values = dict(part.split("=", 1) for part in value.split(";") if "=" in part)
            value = values.get("https") or values.get("http")
        return value if value and "://" in value else "http://" + value if value else None
    except OSError:
        return None


def connection_environment():
    """Repair only a dead inherited loopback proxy, using the existing OS one.

    Never change global settings, invent a remote proxy, print environment
    values or bypass TLS. Explicit working/custom proxies remain authoritative.
    """
    env = dict(os.environ)
    current = env.get("HTTPS_PROXY") or env.get("https_proxy") or env.get("ALL_PROXY") or env.get("all_proxy")
    if current and _local_proxy_available(current) is False:
        fallback = _windows_proxy()
        if fallback and _local_proxy_available(fallback) is True:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env[key] = fallback
            for key in ("ALL_PROXY", "all_proxy"):
                if env.get(key) and _local_proxy_available(env[key]) is False:
                    env.pop(key)
    return env


async def network_probe():
    env = await asyncio.to_thread(connection_environment)
    proxy = env.get("HTTPS_PROXY") or env.get("https_proxy") or env.get("ALL_PROXY") or env.get("all_proxy")
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=8, follow_redirects=False) as client:
            response = await client.get("https://chatgpt.com/backend-api/codex/models")
        return dict(passed=200 <= response.status_code < 500 and response.status_code not in {407, 429},
                    http_status=response.status_code, level="unauthenticated_https_reachability_only", model_calls=0)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return dict(passed=False, error_type=type(exc).__name__, level="https_reachability", model_calls=0)


@dataclass(frozen=True)
class CallLease:
    generation: int
    half_open: bool


class CliRuntimeGuard:
    def __init__(self, *, probe=None, on_event=None, clock=time.monotonic, threshold=2, resume_gap_seconds=90):
        self.probe = probe or network_probe
        self.on_event = on_event
        self.clock = clock
        self.threshold = threshold
        self.resume_gap_seconds = resume_gap_seconds
        self.state = "needs_check"
        self.reason = "startup"
        self.failures = 0
        self.generation = 0
        self.last_tick = clock()
        self.half_open_inflight = False
        self.last_check = None
        self.condition = asyncio.Condition()
        self.probe_lock = asyncio.Lock()

    def snapshot(self):
        messages = {
            "ready": "连接正常，按原预算执行。",
            "needs_check": "正在准备连接检查。",
            "checking": "正在检查连接，尚未新增模型调用。",
            "paused": "检测到运行中断，已暂停新调用，先检查连接。",
            "half_open": "基础连接已可达，等待一次原预算内调用确认恢复。",
            "manual_pause": "连接尚未恢复，后续调用已暂停；请检查连接后继续。",
        }
        return dict(state=self.state, reason=self.reason, consecutive_failures=self.failures,
                    generation=self.generation, message=messages[self.state],
                    retry_required=self.state == "manual_pause", last_check=self.last_check)

    def _change(self, state, reason):
        self.state, self.reason = state, reason
        if self.on_event:
            self.on_event(dict(type="runtime.state", **self.snapshot()))

    async def observe_gap(self, seconds):
        async with self.condition:
            self.last_tick = self.clock()
            if seconds > self.resume_gap_seconds and self.state != "manual_pause" and self.reason != "host_or_scheduler_gap":
                self.generation += 1
                self.half_open_inflight = False
                self._change("paused", "host_or_scheduler_gap")
                self.condition.notify_all()

    async def _check(self):
        async with self.probe_lock:
            async with self.condition:
                if self.state not in {"needs_check", "paused", "manual_pause"}:
                    return self.snapshot()
                generation = self.generation
                self._change("checking", self.reason)
            try:
                result = await self.probe()
            except asyncio.CancelledError:
                async with self.condition:
                    self._change("manual_pause", "connection_check_cancelled")
                    self.condition.notify_all()
                raise
            except Exception as exc:
                result = dict(passed=False, error_type=type(exc).__name__, model_calls=0)
            async with self.condition:
                self.last_tick = self.clock()
                if generation == self.generation:
                    self.last_check = result
                    self._change("half_open" if result.get("passed") else "manual_pause", "reachability_checked")
                self.condition.notify_all()
                return self.snapshot()

    async def recheck(self):
        """Explicit zero-model-call recovery; never replay a failed operation."""
        return await self._check()

    async def before_call(self, on_event=None):
        observed = self.clock()
        await self.observe_gap(observed - self.last_tick)
        last_wait_state = None
        while True:
            async with self.condition:
                self.last_tick = self.clock()
                if self.state == "ready":
                    return CallLease(self.generation, False)
                if self.state == "half_open" and not self.half_open_inflight:
                    self.half_open_inflight = True
                    return CallLease(self.generation, True)
                if self.state in {"needs_check", "paused"}:
                    check = True
                else:
                    check = False
                    if on_event and last_wait_state != self.state:
                        on_event(dict(type="process.connection_wait", runtime=self.snapshot()))
                        last_wait_state = self.state
                    await self.condition.wait()
            if check:
                await self._check()

    async def after_call(self, lease, error=None):
        async with self.condition:
            self.last_tick = self.clock()
            if lease.generation != self.generation:
                return  # A pre-pause success cannot erase a newer outage.
            if lease.half_open:
                self.half_open_inflight = False
                if error is None:
                    self.failures = 0
                    self._change("ready", "real_cli_completed")
                else:
                    if transport_failure(error):
                        self.failures += 1
                    self._change("manual_pause", "recovery_call_incomplete")
            elif error and transport_failure(error):
                self.failures += 1
                if self.failures >= self.threshold:
                    self.generation += 1
                    self._change("manual_pause", "consecutive_transport_failures")
            elif error is None and self.state == "ready":
                self.failures = 0
            self.condition.notify_all()
