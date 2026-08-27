from __future__ import annotations

import asyncio

from demopilot.models import DemoRequest
from demopilot.providers.compatible import OpenAICompatibleAgentProvider


def test_compatible_provider_requests_json_output(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"goal":"ok"}'}}]}

    class FakeClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, endpoint, *, headers, json):
            captured.update(endpoint=endpoint, headers=headers, payload=json)
            return FakeResponse()

    monkeypatch.setattr("demopilot.providers.compatible.httpx.AsyncClient", FakeClient)
    provider = OpenAICompatibleAgentProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    request = DemoRequest(
        client_name="测试客户",
        project_name="测试项目",
        industry="零售",
        scenario="测试 JSON 输出",
        audience="运营负责人",
        must_haves=["风险预警"],
    )

    result = asyncio.run(provider.run_agent("brief", request, {}))

    assert result == {"goal": "ok"}
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["max_tokens"] == 4096
    assert captured["payload"]["temperature"] == 0.1
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert "JSON" in captured["payload"]["messages"][0]["content"]


def test_compatible_provider_assigns_builder_full_output_budget(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"files":{}}'}}]}

    class FakeClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, endpoint, *, headers, json):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("demopilot.providers.compatible.httpx.AsyncClient", FakeClient)
    provider = OpenAICompatibleAgentProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    request = DemoRequest(
        client_name="测试客户",
        project_name="测试项目",
        industry="零售",
        scenario="测试 Builder 输出预算",
        audience="运营负责人",
        must_haves=["风险预警"],
    )

    asyncio.run(provider.run_agent("builder", request, {}))

    assert captured["payload"]["max_tokens"] == 8192


def test_compatible_provider_retries_empty_json_content(monkeypatch):
    contents = iter(["", '{"goal":"recovered"}'])
    payloads: list[dict] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": next(contents)}}]}

    class FakeClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, endpoint, *, headers, json):
            payloads.append(json)
            return FakeResponse()

    monkeypatch.setattr("demopilot.providers.compatible.httpx.AsyncClient", FakeClient)
    provider = OpenAICompatibleAgentProvider(
        name="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    request = DemoRequest(
        client_name="测试客户",
        project_name="测试项目",
        industry="零售",
        scenario="测试 JSON 重试",
        audience="运营负责人",
        must_haves=["风险预警"],
    )

    result = asyncio.run(provider.run_agent("brief", request, {}))

    assert result == {"goal": "recovered"}
    assert len(payloads) == 2
    assert "上次返回为空" in payloads[1]["messages"][1]["content"]
