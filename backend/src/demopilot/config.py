from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[3] / ".data"


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(1, min(value, maximum))


@dataclass(frozen=True, slots=True)
class CompatibleProviderSettings:
    name: str
    api_key: str
    base_url: str
    model: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


@dataclass(slots=True)
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    enable_claude: bool = field(
        default_factory=lambda: os.getenv("DEMOPILOT_ENABLE_CLAUDE", "false").lower()
        in {"1", "true", "yes"}
    )
    max_agent_calls: int = field(
        default_factory=lambda: _positive_int("DEMOPILOT_MAX_AGENT_CALLS", 18, 30)
    )
    max_revision_rounds: int = field(
        default_factory=lambda: _positive_int("DEMOPILOT_MAX_REVISIONS", 4, 4)
    )
    max_parallel_agents: int = field(
        default_factory=lambda: _positive_int("DEMOPILOT_MAX_PARALLEL_AGENTS", 2, 4)
    )
    allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    )

    def compatible_providers(self) -> tuple[CompatibleProviderSettings, ...]:
        return (
            CompatibleProviderSettings(
                name="deepseek",
                api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            ),
            CompatibleProviderSettings(
                name="aihubmix",
                api_key=os.getenv("AIHUBMIX_API_KEY", ""),
                base_url=os.getenv("AIHUBMIX_BASE_URL", "https://aihubmix.com/v1"),
                model=os.getenv("AIHUBMIX_MODEL", "gpt-5.5"),
            ),
            CompatibleProviderSettings(
                name="zju",
                api_key=os.getenv("ZJU_API_KEY", ""),
                base_url=os.getenv("ZJU_BASE_URL", "https://zjuapi.com/v1"),
                model=os.getenv("ZJU_MODEL", "gpt-4o"),
            ),
        )
