from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from .harness import SandboxWorkspace
from .interaction_contract import contract_tests

_SAFE_SELECTOR = re.compile(r"^[#.][A-Za-z][A-Za-z0-9_-]*$")


def _shared_interaction_tests(run: Any) -> list[dict[str, Any]]:
    """Use the frozen team contract, never Builder's self-declared acceptance."""

    return contract_tests(run.outputs.get("interaction_contract"))


def _run_declared_interactions(page: Any, page_uri: str, workspace: SandboxWorkspace) -> tuple[list[str], list[str]]:
    """Execute the frozen, data-only shared contract for every customer must-have."""

    if workspace.run.request.provider == "mock":
        return [], []
    checks: list[str] = []
    issues: list[str] = []
    declared = _shared_interaction_tests(workspace.run)
    required = list(workspace.run.request.must_haves)
    declared_requirements = {
        str(item.get("requirement", "")).strip() for item in declared
    }
    for requirement in required:
        if requirement not in declared_requirements:
            issues.append(f"共享交互协议缺少 must-have：{requirement}")

    for test in declared:
        requirement = str(test.get("requirement", "")).strip()
        if requirement not in required:
            continue
        try:
            steps = test.get("steps", [])
            assertion = test.get("assertion", {})
            if not isinstance(steps, list) or not steps or not isinstance(assertion, dict):
                raise ValueError("步骤或断言为空")
            if len(steps) > 10:
                raise ValueError("步骤超过 10 个")
            page.goto(page_uri, wait_until="load", timeout=15_000)
            assertion_selector = str(assertion.get("selector", ""))
            if not _SAFE_SELECTOR.fullmatch(assertion_selector):
                raise ValueError("断言选择器必须是简单 ID 或 class")
            assertion_locator = page.locator(assertion_selector)
            before_text = assertion_locator.first.text_content() if assertion_locator.count() else None
            for step in steps:
                if not isinstance(step, dict):
                    raise ValueError("步骤格式错误")
                action = str(step.get("action", ""))
                selector = str(step.get("selector", ""))
                if not _SAFE_SELECTOR.fullmatch(selector):
                    raise ValueError("步骤选择器必须是简单 ID 或 class")
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=5_000)
                value = str(step.get("value", ""))
                if action == "click":
                    locator.click(timeout=5_000)
                elif action == "fill":
                    locator.fill(value, timeout=5_000)
                elif action == "select":
                    try:
                        locator.select_option(label=value, timeout=5_000)
                    except Exception:
                        locator.select_option(value=value, timeout=5_000)
                else:
                    raise ValueError(f"不支持的动作：{action}")
                page.wait_for_timeout(80)

            assertion_locator = page.locator(assertion_selector)
            count = assertion_locator.count()
            text_value = " ".join(
                (assertion_locator.nth(index).text_content() or "") for index in range(count)
            )
            contains = assertion.get("text_contains", [])
            excludes = assertion.get("text_not_contains", [])
            contains_values = [contains] if isinstance(contains, str) else contains
            excludes_values = [excludes] if isinstance(excludes, str) else excludes
            missing_contains = (
                ["<invalid text_contains>"]
                if not isinstance(contains_values, list)
                else [str(value) for value in contains_values if str(value) not in text_value]
            )
            if missing_contains:
                raise AssertionError(
                    "期望文本未出现：missing="
                    + repr(missing_contains[:4])
                    + "; actual="
                    + repr(text_value[:180])
                )
            present_excludes = (
                ["<invalid text_not_contains>"]
                if not isinstance(excludes_values, list)
                else [str(value) for value in excludes_values if str(value) in text_value]
            )
            if present_excludes:
                raise AssertionError(
                    "应排除的文本仍然出现：present=" + repr(present_excludes[:4])
                )
            if "count_min" in assertion and count < int(assertion["count_min"]):
                raise AssertionError("元素数量低于下限")
            if "count_max" in assertion and count > int(assertion["count_max"]):
                raise AssertionError("元素数量超过上限")
            if assertion.get("text_changed") and text_value == (before_text or ""):
                raise AssertionError("操作前后文本未变化")
            checks.append(f"Chromium 已按共享协议执行 must-have：{requirement}")
        except Exception as exc:
            issues.append(f"must-have 浏览器测试失败：{requirement}（{str(exc)[:160]}）")
    return checks, issues


async def verify_browser_interactions(
    run_id: str,
    run_dir: Path,
    workspace: SandboxWorkspace,
) -> dict[str, Any]:
    """Exercise the delivered page in Chromium and retain screenshot evidence."""

    return await asyncio.to_thread(
        _verify_browser_interactions_sync, run_id, run_dir, workspace
    )


def _verify_browser_interactions_sync(
    run_id: str,
    run_dir: Path,
    workspace: SandboxWorkspace,
) -> dict[str, Any]:
    """Keep Playwright subprocess management off the FastAPI event loop."""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "status": "unavailable",
            "checks": [],
            "issues": [],
            "open_gates": ["Playwright 未安装，未执行真实浏览器交互验证"],
            "console_errors": [],
        }

    page_path = (run_dir / "artifacts" / "demo" / "index.html").resolve()
    checks: list[str] = []
    issues: list[str] = []
    console_errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            page.goto(page_path.as_uri(), wait_until="load", timeout=15_000)
            advance = page.locator("#advanceButton")
            if advance.count() and not advance.is_visible():
                view_id = advance.evaluate(
                    "element => element.closest('.view') ? element.closest('.view').id : ''"
                )
                if view_id:
                    destination = page.locator(f'.nav-item[data-target="{view_id}"]')
                    if destination.count() and destination.is_visible():
                        destination.click(timeout=8_000)
            advance.wait_for(state="visible", timeout=8_000)
            before = page.locator("#progressLabel").text_content()
            advance.click(timeout=8_000)
            after = page.locator("#progressLabel").text_content()
            if before != after:
                checks.append("Chromium 中推进按钮确实改变三幕故事进度")
            else:
                issues.append("Chromium 中推进按钮未改变三幕故事进度")
            navigation = page.locator(".nav-item")
            if navigation.count() >= 2:
                navigation.nth(1).click(timeout=8_000)
                classes = navigation.nth(1).get_attribute("class") or ""
                if "active" in classes.split():
                    checks.append("Chromium 中导航切换确实更新高亮状态")
                else:
                    issues.append("Chromium 中导航切换未更新高亮状态")
            else:
                issues.append("Chromium 中没有足够的导航项可验证")
            declared_checks, declared_issues = _run_declared_interactions(
                page, page_path.as_uri(), workspace
            )
            checks.extend(declared_checks)
            issues.extend(declared_issues)
            screenshot = page.screenshot(full_page=True, type="png")
            workspace.write_bytes("artifacts/qa/browser-evidence.png", screenshot)
            browser.close()
    except Exception as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message:
            return {
                "status": "unavailable",
                "checks": checks,
                "issues": [],
                "open_gates": ["Chromium 运行时未安装，未执行真实浏览器交互验证"],
                "console_errors": console_errors,
            }
        issues.append(f"Chromium 交互验证异常：{message[:240]}")

    if console_errors:
        issues.append(f"浏览器控制台出现 {len(console_errors)} 个错误")
    return {
        "status": "passed" if not issues else "failed",
        "checks": checks,
        "issues": issues,
        "open_gates": [],
        "console_errors": console_errors[:10],
        "evidence": f"/api/runs/{run_id}/files/artifacts/qa/browser-evidence.png",
    }
