from __future__ import annotations

from typing import Any

from ..models import DemoRequest
from ..reviewer import default_review_rubric


class MockAgentProvider:
    """Deterministic provider: honest local demo mode, not an external LLM."""

    name = "mock"

    async def run_agent(
        self,
        agent_id: str,
        request: DemoRequest,
        context: dict[str, Any],
        *,
        iteration: int = 0,
    ) -> dict[str, Any]:
        must_haves = request.must_haves or ["数据总览", "核心流程", "结果导出"]
        if agent_id == "brief":
            return {
                "goal": f"为{request.client_name}生成一套可讲解、可操作、可复核的售前 Demo",
                "problem": request.scenario,
                "primary_user": request.audience,
                "demo_scope": must_haves,
                "success_criteria": ["90 秒内呈现核心价值", "三步内完成主任务", "数据边界清晰"],
                "assumptions": ["仅使用受控样例数据", "销售交付前复核客户文案"],
                "questions": ["真实数据源和权限范围待客户确认"],
                "non_goals": ["不接入客户生产系统", "不承诺未经验证的收益"],
            }
        if agent_id == "manager":
            return {
                "objective": f"交付 {request.project_name} 的可交互 Demo 包",
                "workstreams": ["需求洞察", "产品故事", "体验规范", "构建", "产物验证"],
                "parallel_groups": [["product", "experience", "reviewer"]],
                "acceptance_criteria": ["页面可独立打开", "核心需求有映射", "QA 审查最终产物"],
                "risks": ["客户信息不足", "受控数据与生产数据存在差异"],
                "call_budget": 9,
            }
        if agent_id == "discovery":
            return {
                "problem_statement": request.scenario,
                "primary_user": request.audience,
                "value_hypothesis": f"让{request.audience}在一次演示中看见流程提效与业务结果。",
                "success_signals": ["核心任务可在 3 步内完成", "关键状态可视化", "结果可追溯"],
                "assumptions": ["使用演示数据，不连接客户生产系统", "由销售在交付前复核文案"],
            }
        if agent_id == "product":
            return {
                "demo_story": [
                    "从业务概览发现待处理事项",
                    f"进入{must_haves[0]}完成关键操作",
                    "查看自动生成的结果与价值指标",
                ],
                "features": must_haves,
                "screens": ["指挥台", "任务工作区", "洞察与结果"],
                "north_star": "Time to first value under 90 seconds",
            }
        if agent_id == "experience":
            return {
                "design_principles": ["信息克制", "层级清晰", "状态可感知"],
                "visual_direction": request.brand_tone,
                "primary_color": request.primary_color,
                "components": ["指标卡片", "任务时间线", "洞察侧栏", "行动按钮"],
                "accessibility": ["文本对比度优先", "完整键盘焦点", "尊重减少动画设置"],
            }
        if agent_id == "contract":
            return {
                "requirements": [
                    {
                        "requirement": requirement,
                        "screen": f"{requirement}工作台",
                        "outcome": f"完成{requirement}后显示明确结果",
                        "steps": [
                            {
                                "action": "click",
                                "purpose": f"执行{requirement}的核心演示动作",
                            }
                        ],
                        "assertion": {
                            "text_contains": [f"{requirement} 已完成"],
                            "text_not_contains": [],
                            "text_changed": True,
                        },
                    }
                    for requirement in must_haves
                ],
                "assumptions": ["全部交互使用本地虚构数据"],
            }
        if agent_id == "builder":
            contract = context.get("interaction_contract", {})
            contract_requirements = contract.get("requirements", []) if isinstance(contract, dict) else []
            return {
                "implementation": "静态交互式客户 Demo，可直接打开或托管",
                "data_mode": "controlled_fixture",
                "interactions": ["导航切换", "任务状态推进", "动态提示", "方案下载"],
                "interaction_tests": [
                    item["test"]
                    for item in contract_requirements
                    if isinstance(item, dict) and isinstance(item.get("test"), dict)
                ],
                "deliverables": ["客户 Demo", "需求规格", "销售讲解词", "QA 报告", "ZIP 归档"],
                "content_notes": ["不展示未经验证的客户收益", "在页面标注样例数据边界"],
                "revision_response": (
                    ["已根据 QA 反馈重新生成受控产物"] if iteration else []
                ),
            }
        if agent_id == "reviewer":
            if context.get("review_phase", {}).get("mode") == "rubric":
                rubric = default_review_rubric(request)
                return {
                    "criteria": rubric["criteria"],
                    "hard_gates": rubric["hard_gates"],
                    "risk_focus": ["交互真实性", "模板兜底标识", "样例数据边界"],
                    "reviewer_notes": ["最终结论必须绑定验证器和 Chromium 证据"],
                }
            validation = context.get("artifact_validation", {})
            issues = validation.get("issues", [])
            return {
                "status": "reviewed" if not issues else "revision_required",
                "decision": "pass" if not issues else "revise",
                "dimension_scores": {
                    "requirement_coverage": 25,
                    "interaction": 20,
                    "artifact": 15,
                    "safety": 15,
                    "demo_clarity": 13,
                    "provenance": 10,
                },
                "checks": [
                    *validation.get("checks", []),
                    "需求字段完整并已映射到演示故事",
                ],
                "issues": [
                    {
                        "severity": "high",
                        "category": "quality",
                        "requirement": "硬性质量门禁",
                        "evidence": issue,
                        "root_cause": "最终产物未满足验证器契约",
                        "repair_instruction": "修复实际产物后重新验证",
                        "verification": "重新运行产物与 Chromium 验证",
                    }
                    for issue in issues
                ],
                "scope_boundaries": ["纯展示型静态 Demo", "使用本地虚构样例数据"],
                "open_gates": [],
                "confidence": 1,
                "reviewer_notes": ["Mock Reviewer 仅验证确定性证据链"],
            }
        raise ValueError(f"Unknown agent: {agent_id}")
