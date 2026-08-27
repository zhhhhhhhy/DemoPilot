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


ProviderName = Literal["mock", "claude", "deepseek", "aihubmix", "zju"]


class DemoRequest(BaseModel):
    client_name: str = Field(min_length=2, max_length=80)
    project_name: str = Field(min_length=2, max_length=100)
    industry: str = Field(min_length=2, max_length=80)
    scenario: str = Field(min_length=10, max_length=2000)
    audience: str = Field(min_length=2, max_length=200)
    must_haves: list[str] = Field(default_factory=list, max_length=12)
    brand_tone: str = Field(default="专业、克制、可信", max_length=100)
    primary_color: str = Field(default="#0071e3", pattern=r"^#[0-9A-Fa-f]{6}$")
    provider: ProviderName = "deepseek"
    require_execution_approval: bool = False

    @field_validator("must_haves")
    @classmethod
    def clean_must_haves(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip()
            if item and item not in cleaned:
                cleaned.append(item[:120])
        return cleaned


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
