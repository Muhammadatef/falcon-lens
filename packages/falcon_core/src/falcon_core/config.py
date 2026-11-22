"""Environment configuration (variables documented in .env.example)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All variables are optional; empty values behave as unset."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore", case_sensitive=False)

    # Runtime mode
    fl_env: str = "local"
    fl_sovereign_mode: bool = False
    fl_public_base_url: str = "https://localhost:8443"

    # Cloud LLM
    anthropic_api_key: SecretStr | None = None
    fl_cloud_model_investigator: str = "claude-sonnet-5-5"
    fl_cloud_model_vision: str = "claude-sonnet-5-5"
    fl_cloud_model_extractor: str = "claude-haiku-5-5"
    fl_cloud_model_responder: str = "claude-haiku-5-5"
    fl_llm_timeout_s: float = 12

    # Local LLM
    ollama_base_url: str = "http://host.docker.internal:11434"
    fl_local_model: str = "gemma3:27b"
    fl_local_vision_model: str = "gemma3:27b"
    fl_local_worker_model: str = "qwen3:4b"
    fl_embed_model: str = "qwen3-embedding:4b"
    fl_embed_dim: int = 2560

    # Feeds
    google_safe_browsing_api_key: SecretStr | None = None
    urlhaus_auth_key: SecretStr | None = None
    fl_feed_openphish_enabled: bool = True

    # Data stores
    postgres_user: str = "falcon"
    postgres_password: SecretStr | None = None
    postgres_db: str = "falcon"
    database_url: SecretStr | None = None
    redis_url: str | None = None

    # API auth
    fl_api_key_pepper: SecretStr | None = None
    fl_sandbox_api_key: SecretStr | None = None
    fl_operator_key: SecretStr | None = None
    fl_mcp_bearer_token: SecretStr | None = None
    fl_webhook_secret: SecretStr | None = None
    fl_rate_limit_per_ip_per_min: int = 30

    # Alerts
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    alert_webhook_url: str | None = None

    # Observability
    otel_exporter_otlp_endpoint: str | None = None

    @property
    def cloud_enabled(self) -> bool:
        """Cloud route is on only with a key and without sovereign mode."""
        return self.anthropic_api_key is not None and not self.fl_sovereign_mode


@lru_cache
def get_settings() -> Settings:
    return Settings()
