from __future__ import annotations

from typing import Any

from .models import DemoRequest

RUBRIC_VERSION = "reviewer-v2"

DEMO_SCOPE_BOUNDARIES = [
    "纯展示型静态售前 Demo",
    "业务数据使用本地虚构样例",
    "业务交互仅在浏览器内模拟并可重置",
    "不连接 ERP、WMS、CRM、数据库、客户真实数据或生产环境",
]

_INTENTIONAL_BOUNDARY_MARKERS = (
    "erp",
    "wms",
    "crm",
    "真实系统",
    "真实集成",
    "真实客户数据",
    "实时数据",
    "实时库存",
    "数据接入",
    "数据同步",
    "数据库",
    "预测",
    "实时计算",
    "后端",
    "审批",
    "权限",
    "角色",
    "生产鉴权",
    "生产部署",
    "生产环境",
    "领域专用后端",
)


def _is_intentional_demo_boundary(value: object) -> bool:
    text = str(value).strip().lower()
    return bool(text) and any(marker in text for marker in _INTENTIONAL_BOUNDARY_MARKERS)


def default_review_rubric(request: DemoRequest) -> dict[str, Any]:
    """Return the stable evidence contract that the Reviewer may enrich, not weaken."""
    return {
        "version": RUBRIC_VERSION,
        "scope": "对照客户 Demo 需求，独立审查最终项目与可复验证据",
        "criteria": [
            {
                "id": "requirement_coverage",
                "name": "需求覆盖",
                "weight": 25,
                "evidence_required": "must_haves 与 feature_coverage 的逐项映射",
            },
            {
                "id": "interaction",
                "name": "交互可用性",
                "weight": 20,
                "evidence_required": "Chromium 实际点击结果与截图",
            },
            {
                "id": "artifact",
                "name": "项目完整性",
                "weight": 15,
                "evidence_required": "文件清单、非空检查与 SHA-256",
            },
            {
                "id": "safety",
                "name": "安全边界",
                "weight": 15,
                "evidence_required": "沙箱、外部资源、危险 DOM 与敏感信息检查",
            },
            {
                "id": "demo_clarity",
                "name": "演示清晰度",
                "weight": 15,
                "evidence_required": "页面内容与三幕销售故事；模型判断仅作建议",
            },
            {
                "id": "provenance",
                "name": "生成可追溯性",
                "weight": 10,
                "evidence_required": "source_mode、工具凭证与构建来源",
            },
        ],
        "hard_gates": [
            "必需产物缺失或为空",
            "客户 must-have 未进入最终 Demo",
            "固定交互在 Chromium 中不可用",
            "安全验证失败",
            "缺少可验证的构建来源",
        ],
        "requirements": list(request.must_haves),
        "demo_boundaries": [
            *DEMO_SCOPE_BOUNDARIES,
            "模拟边界是正确实现，不得列为问题、扣分项或开放项",
        ],
        "total_weight": 100,
    }


def normalize_review_rubric(
    request: DemoRequest, model_rubric: dict[str, Any]
) -> dict[str, Any]:
    rubric = default_review_rubric(request)
    rubric["reviewer_notes"] = model_rubric.get("reviewer_notes", [])
    rubric["risk_focus"] = model_rubric.get("risk_focus", [])
    rubric["model_proposed_criteria"] = model_rubric.get("criteria", [])
    return rubric


def _category(issue: str) -> str:
    text = issue.lower()
    if any(marker in text for marker in ("chromium", "按钮", "导航", "交互")):
        return "interaction"
    if any(marker in text for marker in ("缺少产物", "为空", "文件", "引用")):
        return "artifact"
    if any(marker in text for marker in ("外部", "cookie", "脚本", "安全", "密钥")):
        return "safety"
    if any(marker in text for marker in ("必需能力", "must-have", "未进入 demo")):
        return "requirement"
    return "quality"


def _normalized_model_issues(model_review: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    issues = model_review.get("issues", [])
    if not isinstance(issues, list):
        return normalized
    for index, item in enumerate(issues):
        if isinstance(item, str):
            evidence = item.strip()
            if not evidence:
                continue
            normalized.append(
                {
                    "id": f"reviewer-{index + 1}",
                    "severity": "medium",
                    "category": _category(evidence),
                    "requirement": "评审标准",
                    "evidence": evidence,
                    "root_cause": "Reviewer 未提供更具体的根因",
                    "repair_instruction": "根据证据修正最终产物",
                    "verification": "重新运行对应文件或浏览器验证",
                }
            )
        elif isinstance(item, dict):
            evidence = str(item.get("evidence") or item.get("message") or "").strip()
            if not evidence:
                continue
            normalized.append(
                {
                    "id": str(item.get("id") or f"reviewer-{index + 1}"),
                    "severity": str(item.get("severity") or "medium"),
                    "category": str(item.get("category") or _category(evidence)),
                    "requirement": str(item.get("requirement") or "评审标准"),
                    "evidence": evidence,
                    "root_cause": str(
                        item.get("root_cause") or "Reviewer 未提供更具体的根因"
                    ),
                    "repair_instruction": str(
                        item.get("repair_instruction") or "根据证据修正最终产物"
                    ),
                    "verification": str(
                        item.get("verification") or "重新运行对应文件或浏览器验证"
                    ),
                }
            )
    return normalized


def normalize_final_review(
    request: DemoRequest,
    model_review: dict[str, Any],
    validation: dict[str, Any],
    rubric: dict[str, Any],
) -> dict[str, Any]:
    """Bind the model review to verifier evidence and force hard-gate consistency."""
    validation_issues = [
        str(item) for item in validation.get("issues", []) if str(item).strip()
    ]
    issues = _normalized_model_issues(model_review)
    for index, evidence in enumerate(validation_issues):
        if any(evidence in str(item.get("evidence", "")) for item in issues):
            continue
        issues.append(
            {
                "id": f"validator-{index + 1}",
                "severity": "high",
                "category": _category(evidence),
                "requirement": "硬性质量门禁",
                "evidence": evidence,
                "root_cause": "需要结合生成文件定位；验证器已确认最终行为不符合约定",
                "repair_instruction": "修复对应文件或交互，不得只修改说明文本",
                "verification": "重新执行产物验证与 Chromium 点击测试",
            }
        )

    feature_coverage = validation.get("feature_coverage", {})
    required = feature_coverage.get("required") or list(request.must_haves)
    missing = set(feature_coverage.get("missing") or [])
    requirement_coverage = []
    for requirement in required:
        related_issue = next(
            (
                item
                for item in issues
                if str(requirement) in str(item.get("requirement", ""))
                or (
                    item.get("category")
                    in {"requirement", "requirement_coverage"}
                    and str(requirement) in str(item.get("evidence", ""))
                )
            ),
            None,
        )
        if requirement in missing:
            status = "missing"
            evidence = "验证器未在最终 Demo 数据与页面中找到"
        elif related_issue:
            status = "insufficient"
            evidence = str(related_issue["evidence"])
        else:
            status = "demonstrated"
            evidence = "验证器确认已进入最终 Demo 数据与页面"
        requirement_coverage.append(
            {
                "requirement": str(requirement),
                "status": status,
                "evidence": evidence,
            }
        )

    browser = validation.get("browser_e2e", {})
    source_mode = validation.get("source_mode", "unknown")
    model_dimensions = model_review.get("dimension_scores", {})
    def bounded_model_score(key: str, maximum: float, fallback: float) -> float:
        value = model_dimensions.get(key, fallback)
        try:
            return min(maximum, max(0.0, float(value)))
        except (TypeError, ValueError):
            return fallback

    coverage_ratio = 1.0
    if required:
        coverage_ratio = (len(required) - len(missing)) / len(required)
    safety_failed = any(_category(item) == "safety" for item in validation_issues)
    requirement_cap = 25 * coverage_ratio
    interaction_cap = 20 if browser.get("status") == "passed" else 0
    artifact_cap = 15 if validation.get("status") == "passed" else 0
    safety_cap = 0 if safety_failed else 15
    provenance_cap = 10 if source_mode != "unknown" else 0
    dimension_scores = {
        "requirement_coverage": round(
            min(requirement_cap, bounded_model_score("requirement_coverage", 25, requirement_cap)), 2
        ),
        "interaction": round(
            min(interaction_cap, bounded_model_score("interaction", 20, interaction_cap)), 2
        ),
        "artifact": round(
            min(artifact_cap, bounded_model_score("artifact", 15, artifact_cap)), 2
        ),
        "safety": round(
            min(safety_cap, bounded_model_score("safety", 15, safety_cap)), 2
        ),
        "demo_clarity": round(bounded_model_score("demo_clarity", 15, 12), 2),
        "provenance": round(
            min(provenance_cap, bounded_model_score("provenance", 10, provenance_cap)), 2
        ),
    }
    severity_deductions = {"critical": 10.0, "high": 6.0, "medium": 3.0, "low": 1.0}
    dimension_by_category = {
        "requirement": "requirement_coverage",
        "requirement_coverage": "requirement_coverage",
        "interaction": "interaction",
        "artifact": "artifact",
        "safety": "safety",
        "demo_clarity": "demo_clarity",
        "quality": "demo_clarity",
        "provenance": "provenance",
    }
    score_adjustments: list[dict[str, Any]] = []
    for issue in issues:
        dimension = dimension_by_category.get(str(issue.get("category", "quality")))
        if not dimension:
            continue
        deduction = severity_deductions.get(str(issue.get("severity", "medium")), 3.0)
        before = dimension_scores[dimension]
        dimension_scores[dimension] = max(0.0, round(before - deduction, 2))
        score_adjustments.append(
            {
                "issue_id": issue["id"],
                "dimension": dimension,
                "deduction": round(before - dimension_scores[dimension], 2),
            }
        )
    raw_open_gates = model_review.get("open_gates", [])
    if not isinstance(raw_open_gates, list):
        raw_open_gates = []
    open_gates = [
        str(gate).strip()
        for gate in raw_open_gates
        if str(gate).strip() and not _is_intentional_demo_boundary(gate)
    ]
    decision = str(model_review.get("decision") or "pass")
    if validation_issues:
        decision = "revise"
    elif decision == "revise" and issues:
        decision = "revise"
    elif issues:
        decision = "revise"
    else:
        decision = "pass_with_open_gates" if open_gates else "pass"
    overall_score = round(sum(dimension_scores.values()), 2)
    if decision == "revise" and overall_score >= 80:
        score_adjustments.append(
            {
                "issue_id": "revision-gate",
                "dimension": "overall",
                "deduction": round(overall_score - 79, 2),
            }
        )
        overall_score = 79.0

    supported_interactions = validation.get("fixed_contract", {}).get(
        "supported_interactions", []
    )
    simulated_features = [str(item) for item in required]
    confidence = model_review.get("confidence", 0.85)
    try:
        confidence = min(1.0, max(0.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.85

    return {
        "status": "revision_required" if decision == "revise" else "reviewed",
        "decision": decision,
        "overall_score": overall_score,
        "rubric_version": rubric.get("version", RUBRIC_VERSION),
        "dimension_scores": dimension_scores,
        "score_adjustments": score_adjustments,
        "requirement_coverage": requirement_coverage,
        "checks": list(validation.get("checks", [])),
        "issues": issues,
        "root_cause_summary": [item["root_cause"] for item in issues],
        "repair_plan": [item["repair_instruction"] for item in issues],
        "verification_plan": [item["verification"] for item in issues],
        "real_features": (
            list(supported_interactions) if browser.get("status") == "passed" else []
        ),
        "simulated_features": simulated_features,
        "scope_boundaries": list(DEMO_SCOPE_BOUNDARIES),
        "open_gates": open_gates,
        "confidence": confidence,
        "evidence": {
            "source_mode": source_mode,
            "artifact_status": validation.get("status", "unknown"),
            "browser_status": browser.get("status", "unknown"),
            "browser_evidence": browser.get("evidence"),
            "manifest": validation.get("manifest", []),
            "validator_issue_count": len(validation_issues),
        },
        "reviewer_notes": model_review.get("reviewer_notes", []),
    }
