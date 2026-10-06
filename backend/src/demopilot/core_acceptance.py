from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from .harness import scan_generated_text

_SAFE_SELECTOR = re.compile(r"^[#.][A-Za-z][A-Za-z0-9_-]*$")
_ALLOWED_ROOTS = {"card", "card-web", "testdata"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _visible_text(page: Any, selector: str) -> str:
    locator = page.locator(selector)
    return " ".join((locator.nth(index).text_content() or "") for index in range(locator.count()))


def _assertions_pass(page: Any, assertions: dict[str, Any], before: dict[str, str]) -> None:
    for selector, expected in assertions.items():
        if not _SAFE_SELECTOR.fullmatch(str(selector)) or not isinstance(expected, dict):
            raise ValueError(f"invalid assertion selector or shape: {selector}")
        actual = _visible_text(page, str(selector))
        missing = [str(value) for value in expected.get("contains", []) if str(value) not in actual]
        present = [str(value) for value in expected.get("excludes", []) if str(value) in actual]
        changed = not expected.get("changed") or actual != before.get(str(selector), "")
        if missing or present or not changed:
            raise AssertionError(
                f"{selector}: missing={missing[:4]}, present={present[:4]}, "
                f"changed={changed}, actual={actual[:240]}"
            )


def _run_browser(page: Any, page_uri: str, acceptance: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    checks: list[str] = []
    issues: list[str] = []
    console_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    tests = acceptance.get("tests", [])
    for test in tests:
        test_id = str(test.get("id", "acceptance-test"))
        try:
            page.goto(page_uri, wait_until="load", timeout=15_000)
            for step in test.get("steps", []):
                if not isinstance(step, dict):
                    raise ValueError("step must be an object")
                selector = str(step.get("selector", ""))
                if not _SAFE_SELECTOR.fullmatch(selector):
                    raise ValueError(f"unsafe selector: {selector}")
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=5_000)
                assertions = step.get("assertions", {})
                before = {
                    str(target): _visible_text(page, str(target))
                    for target in assertions
                    if _SAFE_SELECTOR.fullmatch(str(target))
                } if isinstance(assertions, dict) else {}
                action = str(step.get("action", ""))
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
                    raise ValueError(f"unsupported action: {action}")
                deadline = time.monotonic() + 2.5
                last_error: Exception | None = None
                while True:
                    try:
                        if isinstance(assertions, dict):
                            _assertions_pass(page, assertions, before)
                        break
                    except Exception as exc:  # UI updates may be asynchronous.
                        last_error = exc
                        if time.monotonic() >= deadline:
                            raise last_error from None
                        page.wait_for_timeout(100)
            checks.append(f"Chromium acceptance passed: {test_id}")
        except Exception as exc:
            issues.append(f"Chromium acceptance failed: {test_id} ({str(exc)[:240]})")
    return checks, issues, console_errors


def run_acceptance(
    workspace: Path,
    case_id: str,
    evidence_path: Path | None = None,
    protected_hashes: dict[str, str] | None = None,
    trusted_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Run the authored, visible-UI contract against the latest workspace.

    This function is the publication gate. It never trusts a Builder's final
    message and returns a failed result when Chromium is unavailable.
    """

    workspace = workspace.resolve()
    case_root = workspace / "testdata" / case_id
    card_root = workspace / "card-web"
    acceptance_path = case_root / "acceptance.json"
    input_path = case_root / "inputs.json"
    result: dict[str, Any] = {
        "status": "failed",
        "case_id": case_id,
        "checks": [],
        "issues": [],
        "console_errors": [],
        "changed_paths": [],
        "source_sha256": {},
        "acceptance_sha256": None,
        "evidence": None,
    }
    required = [card_root / name for name in ("index.html", "styles.css", "app.js")]
    if not acceptance_path.is_file() or not input_path.is_file():
        result["issues"].append("testdata inputs or acceptance contract is missing")
        return result
    if not all(path.is_file() for path in required):
        result["issues"].append("card-web must contain index.html, styles.css and app.js")
        return result
    acceptance = json.loads(_text(acceptance_path))
    inputs = json.loads(_text(input_path))
    result["acceptance_sha256"] = _sha256(acceptance_path)
    result["source_sha256"] = {path.name: _sha256(path) for path in required}

    trusted_paths = {Path(item).as_posix() for item in (trusted_paths or set())}
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        if relative in trusted_paths:
            continue
        root = relative.split("/", 1)[0]
        if root not in _ALLOWED_ROOTS:
            result["issues"].append(f"CLI wrote outside allowed roots: {relative}")
            continue
        result["changed_paths"].append(relative)
        if root in {"card", "card-web"} and path.suffix.lower() in {".html", ".css", ".js"}:
            findings = scan_generated_text(relative, _text(path))
            result["issues"].extend(f"{relative}: {finding}" for finding in findings)

    tests = acceptance.get("tests")
    if not isinstance(tests, list) or not tests:
        result["issues"].append("acceptance.json has no executable tests")
    if not isinstance(acceptance.get("expected_result"), list) or not acceptance["expected_result"]:
        result["issues"].append("acceptance.json has no expected_result")

    # The Builder may add derived fixture data, but it cannot edit the authored
    # acceptance or pinned public images that the test itself uses.
    if protected_hashes and result["acceptance_sha256"] != protected_hashes.get("acceptance.json"):
        result["issues"].append("acceptance contract changed during the Builder run")
    for asset in inputs.get("assets", []):
        asset_path = case_root / str(asset.get("relative_path", ""))
        expected_hash = asset.get("sha256")
        protected_hash = protected_hashes.get(str(Path(asset.get("relative_path", "")).as_posix())) if protected_hashes else expected_hash
        if not asset_path.is_file() or _sha256(asset_path) != expected_hash or (protected_hash and _sha256(asset_path) != protected_hash):
            result["issues"].append(f"fixture hash changed or missing: {asset.get('relative_path')}")
        filename = asset_path.name
        source = "\n".join(_text(path) for path in required)
        if filename not in source:
            result["issues"].append(f"card-web does not reference fixture file: {filename}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        result["issues"].append("Playwright is not installed; real browser acceptance did not run")
        return result

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            checks, issues, console_errors = _run_browser(page, card_root.joinpath("index.html").as_uri(), acceptance)
            result["checks"].extend(checks)
            result["issues"].extend(issues)
            result["console_errors"] = console_errors[:20]
            if console_errors:
                result["issues"].append(f"browser console emitted {len(console_errors)} error(s)")
            if evidence_path:
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(evidence_path), full_page=True, type="png")
                result["evidence"] = str(evidence_path)
            browser.close()
    except Exception as exc:
        result["issues"].append(f"Chromium startup or navigation failed: {str(exc)[:240]}")
    result["status"] = "passed" if not result["issues"] else "failed"
    return result
