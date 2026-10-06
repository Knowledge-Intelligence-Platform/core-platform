"""Environment-backed application configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KNOWLEDGE_INTELLIGENCE_",
        case_sensitive=False,
        extra="ignore",
    )

    aws_region: str = "us-east-1"
    platform_name: str = "Knowledge Intelligence Platform"
    knowledge_base_id: str = Field(pattern=r"^[A-Za-z0-9]{10}$")
    knowledge_base_data_source_id: str = Field(default="", pattern=r"^(?:[A-Za-z0-9]{10})?$")
    bedrock_model_id: str = "amazon.nova-lite-v1:0"
    bedrock_max_tokens: int = Field(default=4096, ge=256, le=10000)
    bedrock_prompt_caching_enabled: bool = False
    tasks_enabled: bool = False
    task_allowed_identities: set[str] = Field(default_factory=set)
    task_prefix: str = Field(default="tasks", pattern=r"^[A-Za-z0-9][A-Za-z0-9/_-]*$")
    query_tokens: dict[str, SecretStr] = Field(default_factory=dict)
    s3_bucket: str = ""
    agent_max_search_results: int = Field(default=5, ge=1, le=10)

    slack_enabled: bool = False
    slack_bot_token: SecretStr = SecretStr("")
    slack_signing_secret: SecretStr = SecretStr("")
    slack_max_message_length: int = Field(default=3_500, ge=500, le=4_000)
    slack_conversation_window: int = Field(default=20, ge=6, le=100)
    feedback_prefix: str = "feedback/slack"
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
        if self.tasks_enabled and (
            not self.s3_bucket
            or not self.knowledge_base_data_source_id
            or not self.task_allowed_identities
            or not self.task_allowed_identities.issubset(self.query_tokens)
        ):
            raise ValueError("Tasks require S3, a data source, and allowed query identities.")
        if self.admin_token.get_secret_value() and not self.knowledge_base_data_source_id:
            raise ValueError("KNOWLEDGE_BASE_DATA_SOURCE_ID is required for administrative sync.")
        if any(
            "@" not in email or not token.get_secret_value().strip()
            for email, token in self.query_tokens.items()
        ):
            raise ValueError("QUERY_TOKENS must map account emails to non-empty bearer tokens.")
        values = [token.get_secret_value() for token in self.query_tokens.values()]
        if len(values) != len(set(values)):
            raise ValueError("Each query identity must have a unique bearer token.")
        if (self.slack_enabled or self.session_persistence_enabled) and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required for Slack or conversation persistence.")
        if self.slack_enabled and (
            not self.slack_bot_token.get_secret_value().strip()
            or not self.slack_signing_secret.get_secret_value().strip()
        ):
            raise ValueError(
                "SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET are required when Slack is enabled."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
