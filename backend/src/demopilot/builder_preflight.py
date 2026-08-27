from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from .harness import scan_generated_text
from .interaction_contract import contract_tests
from .models import DemoRun

REQUIRED_FILES = ("demo/index.html", "demo/styles.css", "demo/app.js")
FILE_BUDGETS = {
    "demo/index.html": 10_000,
    "demo/styles.css": 14_000,
    "demo/app.js": 28_000,
}


class _HTMLInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, str] = {}
        self.viewport = False
        self.local_styles = False
        self.local_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        element_id = values.get("id")
        if element_id:
            self.ids[element_id] = tag.lower()
        if tag.lower() == "meta" and values.get("name", "").lower() == "viewport":
            self.viewport = True
        if tag.lower() == "link" and values.get("href") == "styles.css":
            self.local_styles = True
        if tag.lower() == "script" and values.get("src") == "app.js":
            self.local_script = True


def _issue(
    code: str,
    category: str,
    message: str,
    remediation: str,
    *,
    selectors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "message": message,
        "selectors": selectors or [],
        "remediation": remediation,
    }


def _app_data(app_js: str) -> dict[str, Any]:
    match = re.search(r"const data = (\{.*?\});\s*let current", app_js, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def preflight_builder_output(run: DemoRun) -> dict[str, Any]:
    """Cheap hard gate for objective Builder failures before disk and Chromium.

    This deliberately excludes visual taste and sales-story quality. Those remain
    soft Reviewer concerns so subjective judgments cannot deadlock generation.
    """

    builder = run.outputs.get("builder", {})
    files = builder.get("files") if isinstance(builder, dict) else None
    if not isinstance(files, dict):
        if run.request.provider == "mock":
            return {
                "status": "skipped",
                "blocking": False,
                "mode": "controlled_template_fallback",
                "checks": ["Mock 模式未冒充模型代码；将使用受控模板并接受后续真实验证"],
                "issues": [],
                "failure_classes": [],
                "contract_sha256": run.outputs.get("interaction_contract", {}).get(
                    "contract_sha256"
                ),
            }
        return {
            "status": "failed",
            "blocking": True,
            "mode": "agent_generated_files",
            "checks": [],
            "issues": [
                _issue(
                    "FILES_OBJECT_MISSING",
                    "required_files",
                    "Builder 没有返回 files 对象，无法验证真实代码。",
                    "返回且仅返回 demo/index.html、demo/styles.css、demo/app.js 三个字符串文件。",
                )
            ],
            "failure_classes": ["required_files"],
            "contract_sha256": run.outputs.get("interaction_contract", {}).get(
                "contract_sha256"
            ),
        }

    issues: list[dict[str, Any]] = []
    checks: list[str] = []
    missing = [name for name in REQUIRED_FILES if not isinstance(files.get(name), str) or not files[name].strip()]
    extras = sorted(str(name) for name in files if name not in REQUIRED_FILES)
    if missing:
        issues.append(
            _issue(
                "REQUIRED_FILES_MISSING",
                "required_files",
                "Builder 缺少必需文件：" + "、".join(missing),
                "补齐三个完整文件；不要只返回补丁或说明。",
            )
        )
    if extras:
        issues.append(
            _issue(
                "UNEXPECTED_FILES",
                "required_files",
                "Builder 返回了不允许的额外文件：" + "、".join(extras),
                "删除额外文件，只保留三个静态 Web 文件。",
            )
        )
    if not missing and not extras:
        checks.append("三个 Builder 文件齐全且范围正确")

    for name in REQUIRED_FILES:
        content = files.get(name)
        if not isinstance(content, str):
            continue
        size = len(content.encode("utf-8"))
        if size > FILE_BUDGETS[name]:
            issues.append(
                _issue(
                    "FILE_BUDGET_EXCEEDED",
                    "file_budget",
                    f"{name} 为 {size} bytes，超过 {FILE_BUDGETS[name]} bytes 预算。",
                    "去除重复数据和装饰代码，优先保留 must-have 闭环。",
                )
            )
        findings = scan_generated_text(name, content)
        if findings:
            issues.append(
                _issue(
                    "UNSAFE_GENERATED_CODE",
                    "security",
                    f"{name} 命中安全规则：{'、'.join(findings)}",
                    "使用本地数据与安全 DOM API；不得放宽安全规则。",
                )
            )
    if not any(item["category"] in {"file_budget", "security"} for item in issues):
        checks.append("文件预算与预写入安全检查通过")

    index_html = files.get("demo/index.html", "")
    styles_css = files.get("demo/styles.css", "")
    app_js = files.get("demo/app.js", "")
    if not all(isinstance(value, str) for value in (index_html, styles_css, app_js)):
        inventory = _HTMLInventory()
    else:
        inventory = _HTMLInventory()
        try:
            inventory.feed(index_html)
        except Exception as exc:  # HTMLParser is permissive, but preserve evidence.
            issues.append(
                _issue(
                    "HTML_PARSE_FAILED",
                    "html_structure",
                    f"HTML 结构无法解析：{exc}",
                    "返回完整、可解析的 HTML 文档。",
                )
            )

    structural_failures: list[str] = []
    if not inventory.viewport:
        structural_failures.append("移动端 viewport")
    if not inventory.local_styles:
        structural_failures.append("本地 styles.css 引用")
    if not inventory.local_script:
        structural_failures.append("本地 app.js 引用")
    if isinstance(index_html, str) and "未连接客户生产系统" not in index_html:
        structural_failures.append("模拟数据边界标识")
    if structural_failures:
        issues.append(
            _issue(
                "HTML_BASELINE_MISSING",
                "html_structure",
                "页面缺少：" + "、".join(structural_failures),
                "补齐 viewport、本地资源引用和明确的模拟边界文案。",
            )
        )
    else:
        checks.append("HTML 基础结构与模拟边界完整")

    shared_contract = run.outputs.get("interaction_contract", {})
    tests = contract_tests(shared_contract)
    missing_selectors: list[str] = []
    wrong_controls: list[str] = []
    missing_assertions: list[str] = []
    for test in tests:
        steps = test.get("steps", [])
        for step_index, step in enumerate(steps if isinstance(steps, list) else []):
            if not isinstance(step, dict):
                continue
            selector = str(step.get("selector", ""))
            element_id = selector.removeprefix("#")
            tag = inventory.ids.get(element_id)
            if not selector.startswith("#") or not tag:
                missing_selectors.append(selector or "<empty>")
                continue
            action = str(step.get("action", "click"))
            allowed_tags = {
                "fill": {"input", "textarea"},
                "select": {"select"},
                "click": {"button", "a", "input"},
            }.get(action, set())
            if step_index > 0 and tag not in allowed_tags:
                wrong_controls.append(f"{selector}({action}->{tag})")
        assertion = test.get("assertion", {})
        if not isinstance(assertion, dict):
            continue
        assertion_selector = str(assertion.get("selector", ""))
        assertion_id = assertion_selector.removeprefix("#")
        if not assertion_selector.startswith("#") or assertion_id not in inventory.ids:
            missing_selectors.append(assertion_selector or "<empty>")
        expected = [
            str(value)
            for value in assertion.get("text_contains", [])
            if str(value).strip()
        ]
        combined = f"{index_html}\n{app_js}"
        if expected and not all(value in combined for value in expected):
            missing_assertions.extend(value for value in expected if value not in combined)

    missing_selectors = list(dict.fromkeys(missing_selectors))
    if not tests:
        issues.append(
            _issue(
                "CONTRACT_MISSING",
                "contract",
                "缺少冻结的交互契约测试。",
                "保留 Harness 编译的 interaction_contract，不得自行替换。",
            )
        )
    if missing_selectors:
        issues.append(
            _issue(
                "CONTRACT_SELECTORS_MISSING",
                "selector",
                "HTML 未真实声明契约选择器：" + "、".join(missing_selectors[:12]),
                "按原 ID 在 HTML 中创建可见控件和结果区。",
                selectors=missing_selectors[:12],
            )
        )
    if wrong_controls:
        issues.append(
            _issue(
                "CONTRACT_CONTROL_MISMATCH",
                "control_type",
                "契约动作与控件类型不一致：" + "、".join(wrong_controls[:12]),
                "fill 使用 input/textarea，select 使用 select，click 使用可点击原生控件。",
            )
        )
    if missing_assertions:
        issues.append(
            _issue(
                "CONTRACT_ASSERTION_TEXT_MISSING",
                "assertion",
                "代码中缺少契约成功反馈：" + "、".join(missing_assertions[:8]),
                "在对应操作后通过 textContent 写入逐字匹配的可见结果。",
            )
        )
    if tests and not missing_selectors and not wrong_controls and not missing_assertions:
        checks.append("冻结契约的选择器、控件类型和成功反馈均已静态实现")

    if isinstance(app_js, str):
        interaction_failures: list[str] = []
        if not re.search(r"addEventListener\s*\(\s*['\"]click['\"]", app_js):
            interaction_failures.append("click 事件绑定")
        if "advanceButton" not in inventory.ids:
            interaction_failures.append("advanceButton")
        if "nav-item" not in f"{index_html}\n{styles_css}\n{app_js}":
            interaction_failures.append("nav-item")
        if interaction_failures:
            issues.append(
                _issue(
                    "CORE_BINDINGS_MISSING",
                    "action_binding",
                    "核心交互绑定缺少：" + "、".join(interaction_failures),
                    "绑定推进按钮和导航点击事件，并产生真实可见状态变化。",
                )
            )
        else:
            checks.append("核心 click 与导航绑定已声明")

        data = _app_data(app_js)
        story = data.get("story") if isinstance(data.get("story"), list) else []
        features = data.get("features") if isinstance(data.get("features"), list) else []
        if len(story) != 3 or any(not isinstance(item, str) for item in story):
            issues.append(
                _issue(
                    "STORY_DATA_INVALID",
                    "data_contract",
                    "const data.story 必须恰好包含三个字符串。",
                    "按固定 JSON 数据契约返回三幕故事。",
                )
            )
        missing_features = [item for item in run.request.must_haves if item not in features]
        if missing_features:
            issues.append(
                _issue(
                    "MUST_HAVE_DATA_MISSING",
                    "data_contract",
                    "const data.features 未逐字覆盖：" + "、".join(missing_features),
                    "将每个 must-have 原文加入 features 字符串数组。",
                )
            )
        if len(story) == 3 and not missing_features:
            checks.append("三幕故事与 must-have 数据契约通过")

    if isinstance(styles_css, str) and run.request.primary_color.lower() not in styles_css.lower():
        issues.append(
            _issue(
                "PRIMARY_COLOR_MISSING",
                "visual_contract",
                "CSS 未包含客户 primary_color 原始值。",
                "把 primary_color 写入 CSS 变量；视觉审美仍由 Reviewer 软评分。",
            )
        )
    else:
        checks.append("客户主色已进入 CSS")

    failure_classes = list(dict.fromkeys(item["category"] for item in issues))
    return {
        "status": "failed" if issues else "passed",
        "blocking": bool(issues),
        "mode": "agent_generated_files",
        "checks": checks,
        "issues": issues,
        "failure_classes": failure_classes,
        "contract_sha256": (
            shared_contract.get("contract_sha256")
            if isinstance(shared_contract, dict)
            else None
        ),
        "scope": {
            "hard": [
                "required_files",
                "file_budget",
                "security",
                "html_structure",
                "contract",
                "selector",
                "control_type",
                "assertion",
                "action_binding",
                "data_contract",
                "visual_contract.primary_color",
            ],
            "soft_reviewer_only": ["visual_taste", "sales_persuasion", "copy_quality"],
        },
    }
