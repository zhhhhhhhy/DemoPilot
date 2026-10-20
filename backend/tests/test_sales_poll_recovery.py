"""Status observation may recover; non-idempotent writes are never replayed."""
import asyncio
import importlib.util
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("poll_recovery_pilot", ROOT / "scripts/run_sales_benchmark_pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class Client:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.gets = []
        self.posts = []

    async def get(self, url):
        self.gets.append(url)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome.get("code", 200), json=outcome, request=httpx.Request("GET", "http://localhost" + url))

    async def post(self, url):
        self.posts.append(url)


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    async def sleep(_seconds):
        pass
    monkeypatch.setattr(pilot.asyncio, "sleep", sleep)


@pytest.mark.parametrize("failures", [1, 3])
def test_status_connection_recovers_without_replaying_a_write(failures):
    client = Client([*[httpx.RemoteProtocolError("lost read") for _ in range(failures)], dict(active=False, status="published")])
    observed = []
    result = asyncio.run(pilot.wait_idle(client, "same-session", time.monotonic() + 10, on_read_retry=observed.append))
    assert result["status"] == "published"
    assert len(observed) == failures
    assert client.gets == ["/api/sales-core/sessions/same-session"] * (failures + 1)
    assert client.posts == []


def test_persistent_read_failure_has_a_finite_bound():
    client = Client([httpx.ConnectError("offline")] * 4)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(pilot.wait_idle(client, "same-session", time.monotonic() + 10))
    assert len(client.gets) == 4 and client.posts == []


def test_http_business_error_is_not_retried():
    client = Client([dict(code=404)])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(pilot.wait_idle(client, "same-session", time.monotonic() + 10))
    assert len(client.gets) == 1 and client.posts == []


def test_original_deadline_cancels_once_without_a_new_job():
    client = Client([])
    with pytest.raises(TimeoutError):
        asyncio.run(pilot.wait_idle(client, "same-session", time.monotonic() - 1))
    assert client.gets == []
    assert client.posts == ["/api/sales-core/sessions/same-session/cancel"]


def test_active_observation_stays_on_the_same_job():
    client = Client([dict(active=True, status="building"), dict(active=False, status="published")])
    result = asyncio.run(pilot.wait_idle(client, "same-session", time.monotonic() + 10))
    assert result["status"] == "published" and len(client.gets) == 2 and client.posts == []
