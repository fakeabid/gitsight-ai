"""Application settings, loaded from environment variables (and .env in development)."""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Noise patterns are managed via custom repository rules in DB. Default list is empty.
DEFAULT_NOISE_PATTERNS: tuple[str, ...] = ()


def _split_csv(value: object) -> object:
    """Allow `A,B,C` in env vars as well as JSON lists."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "pr-review-service"
    environment: str = "development"
    log_level: str = "INFO"

    service_api_key: SecretStr

    gemini_api_key: SecretStr
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_models: Annotated[list[str], NoDecode] = [
        "gemini-3.5-flash",
        "gemini-flash-latest",
    ]
    gemini_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    gemini_timeout_seconds: int = Field(default=60, ge=5)
    gemini_sdk_max_retries: int = Field(default=2, ge=0, le=6)

    max_chunk_chars: int = Field(default=15_000, ge=1_000)
    max_total_chunks: int = Field(default=5, ge=1, le=20)
    noise_patterns: Annotated[list[str], NoDecode] = list(DEFAULT_NOISE_PATTERNS)
    max_diff_chars: int = Field(default=2_000_000, ge=1_000)

    max_concurrency: int = Field(default=3, ge=1, le=10)
    chunk_max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=2.0, ge=0.0)
    review_timeout_seconds: int = Field(default=90, ge=10)
    graceful_failure: bool = Field(default=False)

    @field_validator("gemini_fallback_models", "noise_patterns", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def model_chain(self) -> list[str]:
        """Primary model first, then fallbacks, de-duplicated, order preserved."""
        return list(dict.fromkeys([self.gemini_model, *self.gemini_fallback_models]))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
