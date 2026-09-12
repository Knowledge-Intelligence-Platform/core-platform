"""Environment-backed application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KNOWLEDGE_INTELLIGENCE_",
        case_sensitive=False,
        extra="ignore",
    )

    aws_region: str = "ap-south-1"
    s3_bucket: str
    s3_prefix: str = "raw/confluence/"
    max_document_size_mb: int = Field(default=50, ge=1, le=500)

    openai_api_key: SecretStr
    openai_model: str
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1, le=4096)
    embedding_batch_size: int = Field(default=16, ge=1, le=256)

    visual_analysis_enabled: bool = True
    visual_analysis_model: str | None = None
    visual_render_dpi: int = Field(default=144, ge=72, le=300)
    visual_max_pages_per_document: int = Field(default=10, ge=1, le=100)

    vector_bucket_name: str
    vector_index_name: str = "platform-knowledge"
    vector_top_k: int = Field(default=25, ge=1, le=100)
    agent_max_search_results: int = Field(default=5, ge=1, le=10)

    ingest_unmapped_documents: bool = True

    registry_directory: Path = Path("tenant-provided registry data")
    registry_document_key: str = ""
    registry_appconfig_application: str = ""
    registry_appconfig_environment: str = "production"
    registry_appconfig_profile: str = "components"
    registry_cache_path: Path = Path("/tmp/registry-last-known-good.yaml")
    github_enabled: bool = False
    github_token: SecretStr = SecretStr("")
    github_api_url: str = "https://api.github.com"

    slack_enabled: bool = False
    slack_bot_token: SecretStr = SecretStr("")
    slack_signing_secret: SecretStr = SecretStr("")
    slack_max_message_length: int = Field(default=3_500, ge=500, le=4_000)
    slack_conversation_window: int = Field(default=20, ge=6, le=100)
    feedback_prefix: str = "feedback/slack"
    diagram_prefix: str = "diagrams/slack"
    public_base_url: str = ""
    admin_token: SecretStr = SecretStr("")

    # Progressive Slack delivery: the answer fills in while it is generated.
    slack_streaming_enabled: bool = True
    slack_stream_interval_seconds: float = Field(default=1.0, ge=0.3, le=5.0)

    # Persist each Slack thread's conversation so it survives a task restart.
    session_persistence_enabled: bool = False
    session_prefix: str = "sessions/slack"

    # Summarize older turns instead of dropping them off a sliding window.
    conversation_summarization_enabled: bool = False
    conversation_summary_ratio: float = Field(default=0.3, ge=0.1, le=0.8)
    conversation_preserve_recent_messages: int = Field(default=10, ge=2, le=50)

    # Structured per-answer timing and retrieval metrics.
    metrics_enabled: bool = True


    @model_validator(mode="after")
    def validate_optional_integrations(self) -> Settings:
        if self.github_enabled and not self.github_token.get_secret_value().strip():
            raise ValueError("GITHUB_TOKEN is required when GitHub is enabled.")
        if self.slack_enabled and (
            not self.slack_bot_token.get_secret_value().strip()
            or not self.slack_signing_secret.get_secret_value().strip()
        ):
            raise ValueError(
                "SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET are required when Slack is enabled."
            )
        return self

    @property
    def max_document_size_bytes(self) -> int:
        return self.max_document_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
