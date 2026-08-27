from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .models import DemoRequest

ALLOWED_ACTIONS = {"click", "fill", "select"}
_ASSERTION_PREFIX = re.compile(r"^(?:页面(?:应|将|会)?|结果区)?(?:明确)?(?:显示|出现|包含|可见)[:：]?\s*")


def _text(value: object, fallback: str, *, maximum: int = 120) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:maximum]
    return fallback[:maximum]


def _strings(value: object, fallback: list[str], *, maximum: int = 4) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        return fallback
    cleaned = [str(item).strip()[:120] for item in values if str(item).strip()]
    return cleaned[:maximum] or fallback


def _assertion_terms(value: object, fallback: list[str]) -> list[str]:
    """Compile descriptive model prose into short literal UI evidence terms."""

    raw_values = [value] if isinstance(value, str) else value
    if not isinstance(raw_values, list):
        return fallback
    terms: list[str] = []
    for raw in raw_values:
        for part in re.split(r"[，,；;。\n]+", str(raw)):
            cleaned = _ASSERTION_PREFIX.sub("", part.strip()).strip(" ：:")
            if cleaned and cleaned not in terms:
                terms.append(cleaned[:60])
            if len(terms) >= 6:
                return terms
    return terms or fallback


def _raw_requirements(raw: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = raw.get("requirements") or raw.get("journeys") or []
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def compile_interaction_contract(
    request: DemoRequest,
    raw: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compile model semantics into an immutable, machine-owned selector contract.

    The model chooses the business journey. The harness owns selector allocation and
    exact requirement coverage so Builder and Runner cannot silently invent different
    interfaces.
    """

    raw = raw if isinstance(raw, dict) else {}
    candidates = _raw_requirements(raw)
    compiled: list[dict[str, Any]] = []
    warnings: list[str] = []
    for requirement_index, requirement in enumerate(request.must_haves, start=1):
        candidate = next(
            (
                item
                for item in candidates
                if str(item.get("requirement", "")).strip() == requirement
            ),
            {},
        )
        if not candidate:
            warnings.append(f"Contract Agent 未返回精确需求，已生成安全默认路径：{requirement}")
        screen = _text(candidate.get("screen"), f"{requirement}工作台", maximum=60)
        outcome = _text(
            candidate.get("outcome"),
            f"页面明确反馈“{requirement} 已完成”",
        )
        raw_steps = candidate.get("steps", [])
        semantic_steps = (
            [item for item in raw_steps if isinstance(item, dict)][:6]
            if isinstance(raw_steps, list)
            else []
        )
        if not semantic_steps:
            semantic_steps = [
                {
                    "action": "click",
                    "purpose": f"执行{requirement}的核心演示动作",
                }
            ]
        route_selector = f"#contract-nav-{requirement_index}"
        view_selector = f"#contract-view-{requirement_index}"
        steps: list[dict[str, str]] = [
            {
                "action": "click",
                "selector": route_selector,
                "value": "",
                "purpose": f"进入{screen}",
            }
        ]
        elements: list[dict[str, str]] = []
        for step_index, step in enumerate(semantic_steps, start=1):
            action = str(step.get("action", "click")).strip().lower()
            if action not in ALLOWED_ACTIONS:
                warnings.append(
                    f"{requirement} 包含不支持动作 {action or 'empty'}，已收敛为 click"
                )
                action = "click"
            selector = f"#contract-{requirement_index}-step-{step_index}"
            value = _text(
                step.get("value"),
                "演示选项" if action == "select" else "演示值",
                maximum=80,
            ) if action in {"fill", "select"} else ""
            purpose = _text(
                step.get("purpose") or step.get("label"),
                f"完成{requirement}的第 {step_index} 步",
            )
            steps.append(
                {
                    "action": action,
                    "selector": selector,
                    "value": value,
                    "purpose": purpose,
                }
            )
            elements.append(
                {
                    "selector": selector,
                    "control": action,
                    "value": value,
                    "purpose": purpose,
                }
            )
        raw_assertion = candidate.get("assertion") or candidate.get("expected") or {}
        raw_assertion = raw_assertion if isinstance(raw_assertion, dict) else {}
        default_success = f"{requirement} 已完成"
        assertion = {
            "selector": f"#contract-{requirement_index}-result",
            "text_contains": _assertion_terms(
                raw_assertion.get("text_contains") or raw_assertion.get("contains"),
                [default_success],
            ),
            "text_not_contains": _strings(
                raw_assertion.get("text_not_contains") or raw_assertion.get("excludes"),
                [],
            ),
            "text_changed": bool(raw_assertion.get("text_changed", True)),
        }
        compiled.append(
            {
                "requirement": requirement,
                "screen": screen,
                "outcome": outcome,
                "route": {
                    "nav_selector": route_selector,
                    "view_selector": view_selector,
                },
                "elements": elements,
                "test": {
                    "requirement": requirement,
                    "steps": steps,
                    "assertion": assertion,
                },
            }
        )

    core = {
        "version": "interaction-contract-v1.1",
        "frozen": True,
        "owner": "contract-agent+harness-compiler",
        "requirements": compiled,
        "coverage": {
            "required": list(request.must_haves),
            "contracted": [item["requirement"] for item in compiled],
            "missing": [],
        },
        "normalization_warnings": warnings,
    }
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **core,
        "contract_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def contract_tests(contract: object) -> list[dict[str, Any]]:
    if not isinstance(contract, dict):
        return []
    requirements = contract.get("requirements", [])
    if not isinstance(requirements, list):
        return []
    return [
        item["test"]
        for item in requirements
        if isinstance(item, dict) and isinstance(item.get("test"), dict)
    ]
