from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .interaction_contract import contract_tests
from .models import DemoRun


def _app_data(app_js: str) -> dict[str, Any]:
    match = re.search(r"const data = (\{.*?\});\s*let current", app_js, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def verify_artifacts(run: DemoRun, run_dir: Path) -> dict[str, Any]:
    artifact_dir = run_dir / "artifacts"
    required = (
        "demo/index.html",
        "demo/styles.css",
        "demo/app.js",
        "demo-spec.json",
        "sales-script.md",
        "qa-report.md",
        "README.md",
    )
    checks: list[str] = []
    issues: list[str] = []
    manifest: list[dict[str, Any]] = []
    for relative in required:
        path = artifact_dir / relative
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if exists else None
        manifest.append({"path": relative, "exists": exists, "bytes": size, "sha256": digest})
        if not exists:
            issues.append(f"缺少产物：{relative}")
        elif size == 0:
            issues.append(f"产物为空：{relative}")
    if not issues:
        checks.append("7 个必需文件均存在且非空")

    index_path = artifact_dir / "demo" / "index.html"
    if index_path.is_file():
        page = index_path.read_text(encoding="utf-8")
        page_checks = {
            "页面包含移动端 viewport": bool(
                re.search(r"(?i)name\s*=\s*['\"]viewport['\"]", page)
            ),
            "页面明确标注未连接生产系统": "未连接客户生产系统" in page,
            "页面加载本地样式和交互脚本": (
                bool(re.search(r"(?i)href\s*=\s*['\"]styles\.css['\"]", page))
                and bool(re.search(r"(?i)src\s*=\s*['\"]app\.js['\"]", page))
            ),
        }
        checks.extend(label for label, passed in page_checks.items() if passed)
        issues.extend(label for label, passed in page_checks.items() if not passed)

    styles_path = artifact_dir / "demo" / "styles.css"
    app_path = artifact_dir / "demo" / "app.js"
    styles = styles_path.read_text(encoding="utf-8") if styles_path.is_file() else ""
    app_js = app_path.read_text(encoding="utf-8") if app_path.is_file() else ""
    combined_web = "\n".join((page if index_path.is_file() else "", styles, app_js))
    unsafe_patterns = {
        "生成页面不得访问外部网络": r"(?i)\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(",
        "生成页面不得嵌入远程资源": r"(?i)(?:src|href)\s*=\s*['\"]https?://",
        "生成页面不得读取 Cookie": r"(?i)document\.cookie",
    }
    for label, pattern in unsafe_patterns.items():
        if re.search(pattern, combined_web):
            issues.append(label)
        else:
            checks.append(label)
    data = _app_data(app_js)
    features = data.get("features") if isinstance(data.get("features"), list) else []
    story = data.get("story") if isinstance(data.get("story"), list) else []
    feature_text = " ".join(str(item) for item in features)
    missing_features = [
        feature for feature in run.request.must_haves if feature not in feature_text
    ]
    if missing_features:
        issues.append("必需能力未进入 Demo：" + "、".join(missing_features))
    else:
        checks.append("全部必需能力均进入 Demo 数据与页面展示")
    generic_story = ["发现问题", "执行任务", "验证价值"]
    product_story = run.outputs.get("product", {}).get("demo_story")
    if len(story) < 3 or any(not isinstance(item, str) for item in story):
        issues.append("三幕演示故事缺失或包含不可展示的数据结构")
    elif product_story and story == generic_story:
        issues.append("模型已提供演示故事，但最终页面静默降级为通用占位故事")
    else:
        checks.append("三幕演示故事已标准化为可展示文本")
    interaction_checks = {
        "推进按钮已绑定故事状态变化": (
            "advanceButton" in app_js
            and bool(re.search(r"addEventListener\s*\(\s*['\"]click['\"]", app_js))
        ),
        "导航已绑定可见状态切换": (
            "nav-item" in combined_web
            and bool(
                re.search(
                    r"classList\.(?:add|toggle)\s*\([^)]*['\"]active['\"]",
                    app_js,
                )
            )
        ),
        "功能卡片由结构化数据渲染": bool(
            re.search(r"data\.features\.(?:map|forEach)\s*\(", app_js)
        ),
    }
    checks.extend(label for label, passed in interaction_checks.items() if passed)
    issues.extend(label for label, passed in interaction_checks.items() if not passed)

    shared_contract = run.outputs.get("interaction_contract", {})
    shared_tests = contract_tests(shared_contract)
    contracted_requirements = [
        str(item.get("requirement", "")).strip() for item in shared_tests
    ]
    missing_contract_requirements = [
        item for item in run.request.must_haves if item not in contracted_requirements
    ]
    selectors: list[str] = []
    for test in shared_tests:
        for step in test.get("steps", []):
            if isinstance(step, dict) and isinstance(step.get("selector"), str):
                selectors.append(step["selector"])
        assertion = test.get("assertion", {})
        if isinstance(assertion, dict) and isinstance(assertion.get("selector"), str):
            selectors.append(assertion["selector"])
    unique_selectors = list(dict.fromkeys(selectors))
    missing_source_selectors = [
        selector
        for selector in unique_selectors
        if selector.removeprefix("#").removeprefix(".") not in combined_web
    ]
    if missing_contract_requirements:
        issues.append(
            "共享交互协议未覆盖需求：" + "、".join(missing_contract_requirements)
        )
    elif not shared_tests:
        issues.append("缺少冻结的内部共享交互协议")
    else:
        checks.append("内部共享交互协议逐字覆盖全部 must-have")
    if missing_source_selectors:
        issues.append(
            "Builder 未实现共享协议选择器：" + "、".join(missing_source_selectors[:12])
        )
    elif unique_selectors:
        checks.append("Builder 文件包含共享协议声明的全部稳定选择器")
    if run.request.primary_color.lower() in styles.lower():
        checks.append("客户主色已写入视觉变量")
    else:
        issues.append("客户主色未写入生成样式")

    provenance = run.outputs.get("build_provenance", {})
    source_mode = provenance.get("source_mode", "unknown")
    if source_mode == "agent_generated_files":
        checks.append("Builder 提供的 HTML/CSS/JS 已通过沙箱落盘和契约验证")
    elif source_mode == "controlled_template_fallback":
        checks.append("使用受控模板回退；未冒充模型生成代码")
    else:
        issues.append("缺少可验证的构建来源记录")

    return {
        "status": "passed" if not issues else "failed",
        "source_mode": source_mode,
        "fixed_contract": {
            "artifact_type": "controlled_static_sales_demo",
            "files": list(required),
            "supported_interactions": ["导航高亮切换", "三幕故事推进", "核心能力卡片", "任务数动态变化"],
            "allowed_fixture_interactions": ["表单操作", "筛选排序", "状态流转", "弹层", "领域看板"],
            "intentional_non_goals": ["真实系统集成", "真实领域数据写入", "生产鉴权与部署"],
        },
        "checks": checks,
        "issues": issues,
        "feature_coverage": {
            "required": run.request.must_haves,
            "rendered": features,
            "missing": missing_features,
        },
        "interaction_coverage": interaction_checks,
        "shared_contract": {
            "status": (
                "passed"
                if shared_tests
                and not missing_contract_requirements
                and not missing_source_selectors
                else "failed"
            ),
            "contract_sha256": (
                shared_contract.get("contract_sha256")
                if isinstance(shared_contract, dict)
                else None
            ),
            "required": list(run.request.must_haves),
            "contracted": contracted_requirements,
            "missing_requirements": missing_contract_requirements,
            "selectors": unique_selectors,
            "missing_source_selectors": missing_source_selectors,
        },
        "manifest": manifest,
    }
