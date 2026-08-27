from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def safe_url(raw: str) -> str:
    """Remove credentials, query strings and fragments before reporting a URL."""
    parsed = urlsplit(raw)
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, "", ""))


def error_marker(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if not isinstance(error, dict):
        return None
    marker = error.get("code") or error.get("type")
    if not isinstance(marker, str):
        return None
    return "".join(character for character in marker if character.isalnum() or character in "_-.")[:80]


async def check_chat_api(
    client: httpx.AsyncClient,
    name: str,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly API_OK"}],
        "stream": False,
    }
    if model.lower().startswith(("gpt-5", "o1", "o3", "o4")):
        payload["max_completion_tokens"] = 16
    else:
        payload["max_tokens"] = 16
        payload["temperature"] = 0
    result: dict[str, Any] = {
        "name": name,
        "kind": "chat_completion",
        "endpoint": safe_url(base_url),
        "model": model,
    }
    try:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        result["status_code"] = response.status_code
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["ok"] = response.status_code == 200
        if response.status_code == 200:
            try:
                body = response.json()
                content = body["choices"][0]["message"].get("content")
                result["response_shape_ok"] = isinstance(content, str)
                usage = body.get("usage", {})
                if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
                    result["total_tokens"] = usage["total_tokens"]
            except (ValueError, KeyError, IndexError, TypeError):
                result["response_shape_ok"] = False
        else:
            result["error_code"] = error_marker(response)
    except httpx.TimeoutException:
        result.update(ok=False, error_code="timeout")
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    except httpx.HTTPError as exc:
        result.update(ok=False, error_code=type(exc).__name__)
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result


async def check_hugging_face(
    client: httpx.AsyncClient, token: str, configured_endpoint: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        response = await client.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}"},
        )
        results.append(
            {
                "name": "Hugging Face token",
                "kind": "authentication",
                "endpoint": "https://huggingface.co/api/whoami-v2",
                "status_code": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "ok": response.status_code == 200,
                "error_code": None if response.status_code == 200 else error_marker(response),
            }
        )
    except httpx.TimeoutException:
        results.append(
            {
                "name": "Hugging Face token",
                "kind": "authentication",
                "endpoint": "https://huggingface.co/api/whoami-v2",
                "ok": False,
                "error_code": "timeout",
            }
        )
    except httpx.HTTPError as exc:
        results.append(
            {
                "name": "Hugging Face token",
                "kind": "authentication",
                "endpoint": "https://huggingface.co/api/whoami-v2",
                "ok": False,
                "error_code": type(exc).__name__,
            }
        )
    results.append(await check_endpoint(client, "HF mirror", configured_endpoint))
    return results


async def check_endpoint(
    client: httpx.AsyncClient, name: str, endpoint: str
) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "name": name,
        "kind": "endpoint_reachability",
        "endpoint": safe_url(endpoint),
    }
    try:
        async with client.stream("GET", endpoint, headers={"Range": "bytes=0-0"}) as response:
            result["status_code"] = response.status_code
            result["ok"] = 200 <= response.status_code < 400
    except httpx.TimeoutException:
        result.update(ok=False, error_code="timeout")
    except httpx.HTTPError as exc:
        result.update(ok=False, error_code=type(exc).__name__)
    result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result


async def main() -> int:
    values = {key: value for key, value in dotenv_values(ENV_PATH).items() if value}
    required_groups = {
        "Qwen / DashScope": ("DASHSCOPE_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL"),
        "AIHubMix": ("AIHUBMIX_API_KEY", "AIHUBMIX_BASE_URL", "AIHUBMIX_MODEL"),
        "ZJU API": ("ZJU_API_KEY", "ZJU_API_BASE_URL", "ZJU_API_MODEL"),
        "DeepSeek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"),
    }
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        chat_tasks = []
        for name, keys in required_groups.items():
            if all(values.get(key) for key in keys):
                chat_tasks.append(
                    check_chat_api(
                        client,
                        name,
                        values[keys[0]],
                        values[keys[1]],
                        values[keys[2]],
                    )
                )
            else:
                results.append(
                    {
                        "name": name,
                        "kind": "chat_completion",
                        "ok": False,
                        "error_code": "missing_configuration",
                    }
                )
        results.extend(await asyncio.gather(*chat_tasks))
        if values.get("HF_TOKEN") and values.get("HF_ENDPOINT"):
            results.extend(
                await check_hugging_face(client, values["HF_TOKEN"], values["HF_ENDPOINT"])
            )
        else:
            results.append(
                {
                    "name": "Hugging Face",
                    "kind": "authentication",
                    "ok": False,
                    "error_code": "missing_configuration",
                }
            )
        for name, key in (("uv package index", "UV_DEFAULT_INDEX"), ("pip package index", "PIP_INDEX_URL")):
            if values.get(key):
                results.append(await check_endpoint(client, name, values[key]))
            else:
                results.append(
                    {
                        "name": name,
                        "kind": "endpoint_reachability",
                        "ok": False,
                        "error_code": "missing_configuration",
                    }
                )

    summary = {
        "env_file": str(ENV_PATH),
        "secret_values_printed": False,
        "passed": sum(1 for item in results if item.get("ok")),
        "failed": sum(1 for item in results if not item.get("ok")),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
