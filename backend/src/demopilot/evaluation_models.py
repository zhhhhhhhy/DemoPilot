from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .models import ProviderName, utc_now


class EvaluationCase(BaseModel):
    id: str
    name: str
    industry: str
    scenario: str
    audience: str
    must_haves: list[str]
    brand_tone: str = "简洁、可信、现代"
    primary_color: str = "#0071e3"
    difficulty: Literal["basic", "standard", "edge"] = "standard"
    tags: list[str] = Field(default_factory=list)


class EvaluationThresholds(BaseModel):
    min_success_rate: float = Field(default=0.9, ge=0, le=1)
    min_average_score: float = Field(default=80, ge=0, le=100)
    min_browser_pass_rate: float = Field(default=0.9, ge=0, le=1)
    min_feature_coverage_rate: float = Field(default=0.95, ge=0, le=1)
    max_average_agent_calls: float = Field(default=12, ge=1, le=30)


class EvaluationRequest(BaseModel):
    provider: ProviderName = "mock"
    case_ids: list[str] = Field(default_factory=list, max_length=20)
    case_limit: int = Field(default=5, ge=1, le=20)
    concurrency: int = Field(default=2, ge=1, le=3)
    version_label: str = Field(default="local", min_length=1, max_length=60)
    baseline_id: str | None = None
    skill_profile: Literal["baseline", "candidate", "approved"] = "approved"
    first_pass_only: bool = False
    builder_preflight_enabled: bool = True
    thresholds: EvaluationThresholds = Field(default_factory=EvaluationThresholds)

    @model_validator(mode="after")
    def restrict_real_provider_budget(self) -> EvaluationRequest:
        if self.provider != "mock":
            if self.case_limit > 3 or len(self.case_ids) > 3:
                raise ValueError("真实 Provider 每次评测最多允许 3 个用例")
            self.concurrency = 1
        return self


class EvaluationCaseResult(BaseModel):
    case_id: str
    case_name: str
    run_id: str | None = None
    status: Literal["pending", "running", "passed", "failed", "cancelled"] = "pending"
    passed: bool = False
    score: float = Field(default=0, ge=0, le=100)
    failure_category: Literal[
        "none",
        "provider",
        "sandbox",
        "artifact_contract",
        "browser",
        "quality_gate",
        "preflight_security",
        "interaction_contract",
        "data_contract",
        "builder_preflight",
        "budget",
        "cancelled",
        "unknown",
    ] = "none"
    issues: list[str] = Field(default_factory=list)
    source_mode: str = "unknown"
    artifact_status: str = "not_run"
    browser_status: str = "not_run"
    security_status: str = "not_run"
    quality_gate: str = "pending"
    feature_coverage: float = Field(default=0, ge=0, le=1)
    agent_calls: int = Field(default=0, ge=0)
    revision_count: int = Field(default=0, ge=0)
    first_pass_passed: bool = False
    first_pass_score: float = Field(default=0, ge=0, le=100)
    first_pass_browser_status: str = "not_run"
    duration_seconds: float = Field(default=0, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EvaluationMetrics(BaseModel):
    total_cases: int = 0
    completed_cases: int = 0
    passed_cases: int = 0
    first_pass_passed_cases: int = 0
    success_rate: float = 0
    first_pass_success_rate: float = 0
    average_score: float = 0
    first_pass_average_score: float = 0
    browser_pass_rate: float = 0
    feature_coverage_rate: float = 0
    artifact_pass_rate: float = 0
    fallback_rate: float = 0
    revision_rate: float = 0
    average_agent_calls: float = 0
    average_duration_seconds: float = 0
    failure_categories: dict[str, int] = Field(default_factory=dict)


class AcceptanceGate(BaseModel):
    name: str
    actual: float
    operator: Literal[">=", "<="]
    threshold: float
    passed: bool


class EvaluationRun(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    request: EvaluationRequest
    case_ids: list[str] = Field(default_factory=list)
    results: list[EvaluationCaseResult] = Field(default_factory=list)
    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    gates: list[AcceptanceGate] = Field(default_factory=list)
    verdict: Literal["pending", "passed", "failed"] = "pending"
    comparison: dict[str, float | str | None] = Field(default_factory=dict)
    skill_promotion: dict[str, bool | float | str | list[str]] = Field(default_factory=dict)
    active_run_ids: list[str] = Field(default_factory=list)
    cancel_requested: bool = False
    error: str | None = None
    report_url: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
