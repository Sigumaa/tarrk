from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def resolve_env_files() -> tuple[str, str]:
    backend_dir = Path(__file__).resolve().parents[1]
    repo_root = backend_dir.parent
    return (str(backend_dir / ".env"), str(repo_root / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=resolve_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str = Field(default="")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    model_temperature: float = Field(default=0.9, ge=0.0, le=2.0)
    history_limit: int = Field(default=16, ge=1)
    default_max_rounds: int = Field(default=40, ge=1)
    loop_interval_seconds: float = Field(default=0.5, ge=0.0)
    max_consecutive_failures: int = Field(default=3, ge=1)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
