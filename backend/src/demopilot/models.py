from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ProviderName = Literal["mock", "codex_cli", "claude", "deepseek", "aihubmix", "zju"]


class DemoRequest(BaseModel):
    client_name: str = Field(min_length=2, max_length=80)
    project_name: str = Field(min_length=2, max_length=100)
    industry: str = Field(min_length=2, max_length=80)
    scenario: str = Field(min_length=10, max_length=2000)
    audience: str = Field(min_length=2, max_length=200)
    must_haves: list[str] = Field(default_factory=list, max_length=12)
    boundaries: list[str] = Field(default_factory=list, max_length=8)
    priority: str = Field(default="先完成核心可演示闭环", max_length=200)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    # Keep direct API clients backward-compatible while the UI asks the user
    # to confirm the rendered one-page statement before submitting.
    intent_confirmed: bool = True
    brand_tone: str = Field(default="专业、克制、可信", max_length=100)
    primary_color: str = Field(default="#0071e3", pattern=r"^#[0-9A-Fa-f]{6}$")
    provider: ProviderName = "deepseek"
    require_execution_approval: bool = False
    # Evaluation-only context is explicit so the real Codex CLI prompt carries
    # the intent, goal, flow and acceptance method instead of hiding them in a
    # free-form scenario string. These fields are optional for normal runs.
    evaluation_case_id: str | None = Field(default=None, max_length=100)
    evaluation_mode: Literal["full_pipeline", "core_generation"] = "full_pipeline"
    evaluation_difficulty: Literal["simple", "medium", "hard"] | None = None
    evaluation_intent: str | None = Field(default=None, max_length=1200)
    evaluation_goal: str | None = Field(default=None, max_length=1200)
    evaluation_flow_steps: list[str] = Field(default_factory=list, max_length=12)
    evaluation_method: list[str] = Field(default_factory=list, max_length=12)
    evaluation_assets: list[str] = Field(default_factory=list, max_length=24)
    evaluation_asset_sha256: dict[str, str] = Field(default_factory=dict, max_length=24)
    evaluation_browser_contract: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "must_haves",
        "boundaries",
        "acceptance_criteria",
        "constraints",
        "evaluation_flow_steps",
        "evaluation_method",
    )
    @classmethod
    def clean_string_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in cleaned:
                cleaned.append(item[:120])
        return cleaned


def build_intent_statement(request: DemoRequest) -> dict[str, Any]:
    """Build the durable, human-readable contract between intent and delivery.

    The statement is deterministic so the UI, agents, and generated spec all
    inspect the same acceptance surface. Empty optional lists receive explicit
    defaults instead of disappearing from the contract.
    """

    boundaries = request.boundaries or [
        "交付纯展示型静态 Demo，不连接客户生产系统",
        "业务数据使用本地虚构样例，交互仅在浏览器内模拟",
    ]
    acceptance = request.acceptance_criteria or [
        "每项必须能力都有可操作控件和可见结果",
        "生成文件、交互契约与浏览器验证全部通过",
        "Reviewer 能根据证据给出独立结论",
    ]
    constraints = request.constraints or [
        "不引入外部服务、真实客户数据或生产鉴权",
        "失败时保留证据并在下一轮定向返工，不静默降级",
    ]
    return {
        "status": "confirmed" if request.intent_confirmed else "draft",
        "goal": (
            f"为{request.audience}制作{request.project_name}，"
            f"帮助其在{request.scenario}的场景下完成可演示的核心闭环。"
        ),
        "boundary": boundaries,
        "priority": request.priority or "先完成核心可演示闭环",
        "acceptance": acceptance,
        "constraints": constraints,
        "must_haves": list(request.must_haves),
        "evaluation": {
            "case_id": request.evaluation_case_id,
            "mode": request.evaluation_mode,
            "difficulty": request.evaluation_difficulty,
            "intent": request.evaluation_intent,
            "goal": request.evaluation_goal,
            "flow_steps": list(request.evaluation_flow_steps),
            "method": list(request.evaluation_method),
            "assets": list(request.evaluation_assets),
            "asset_sha256": dict(request.evaluation_asset_sha256),
            "browser_contract_version": request.evaluation_browser_contract.get("version"),
        }
        if request.evaluation_case_id
        else None,
        "source": "user_brief_and_article_dimensions",
    }


class AgentEvent(BaseModel):
    id: str
    agent_id: str
    role: str
    status: AgentStatus
    message: str
    iteration: int = Field(default=0, ge=0)
    event_type: Literal["agent", "lifecycle", "approval", "hook", "gate"] = "agent"
    sequence: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ToolReceipt(BaseModel):
    id: str
    tool_name: str
    action: str
    agent_id: str
    status: Literal["succeeded", "failed"]
    input_summary: str
    output_summary: str
    relative_paths: list[str] = Field(default_factory=list)
    sha256: dict[str, str] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class ApprovalRequest(BaseModel):
    id: str
    action: str
    reason: str
    risk: Literal["low", "medium", "high"] = "low"
    requested_by: str
    status: Literal["pending", "approved", "declined", "auto_approved"] = "pending"
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "decline"]


class Artifact(BaseModel):
    name: str
    kind: Literal["demo", "spec", "script", "qa", "archive", "evidence"]
    relative_path: str
    download_url: str


class DemoRun(BaseModel):
    id: str
    status: RunStatus = RunStatus.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    current_agent: str | None = None
    request: DemoRequest
    events: list[AgentEvent] = Field(default_factory=list)
    tool_receipts: list[ToolReceipt] = Field(default_factory=list)
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    agent_calls: int = Field(default=0, ge=0)
    revision_count: int = Field(default=0, ge=0)
    quality_gate: Literal["pending", "passed", "passed_with_open_gates", "failed"] = "pending"
    # Core-generation publication is fail-closed: a completed run can still be
    # hidden/cannot_complete when the independent acceptance gate failed.
    publication_status: Literal["hidden", "published", "cannot_complete"] = "hidden"
    error: str | None = None
    checkpoint: str | None = None
    cancel_requested: bool = False
    resume_count: int = Field(default=0, ge=0)
    last_event_sequence: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    claude_enabled: bool
    providers: dict[str, bool] = Field(default_factory=dict)
