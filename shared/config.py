from functools import lru_cache
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelPrice(BaseModel):
    """USD per million tokens."""

    input: float
    output: float


# Anthropic list prices. Override with the MODEL_PRICES env var (JSON) when they
# change, instead of editing code.
DEFAULT_MODEL_PRICES = {
    "claude-haiku-4-5": ModelPrice(input=1.0, output=5.0),
    "claude-sonnet-5": ModelPrice(input=2.0, output=10.0),
    # Bedrock bills its own rates; Claude API prices are close enough for the dashboard.
    "us.anthropic.claude-opus-4-5-20251101-v1:0": ModelPrice(input=5.0, output=25.0),
    "claude-sonnet-5-5": ModelPrice(input=2.0, output=10.0),
    "claude-opus-5-5": ModelPrice(input=4.0, output=20.0),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://prcopilot:prcopilot@localhost:5432/prcopilot"
    kafka_bootstrap_servers: str = "localhost:9092"

    kafka_topic: str = "pr-events"
    kafka_dlq_topic: str = "pr-events-dlq"
    kafka_partitions: int = 3
    kafka_consumer_group: str = "pr-workers"
    # Single broker, so replication above 1 would make topic creation fail.
    kafka_replication_factor: int = 1
    kafka_max_poll_interval_ms: int = 900_000
    # About two minutes of waiting for the broker on startup before giving up.
    kafka_startup_attempts: int = 15
    # Attempts per message before it is moved to the dead letter topic.
    worker_max_attempts: int = 3
    worker_retry_base_seconds: float = 2.0
    # A review left in "running" this long (worker crashed mid-review) may be reclaimed.
    review_stale_after_seconds: int = 900

    github_webhook_secret: str = ""
    github_app_id: str = ""
    # PEM contents; in Kubernetes this comes from a Secret.
    github_private_key: str = ""
    # Configurable for GitHub Enterprise, a proxy, or the e2e mock server.
    github_api_url: str = "https://api.github.com"

    # "bedrock" uses AWS credentials instead of an API key. Claude models go through Bedrock's
    # Messages API, which accepts this SDK's API version only on Claude 4.7+ and Sonnet 5+
    # (not Haiku 4.5); any other model ID (e.g. us.moonshotai.kimi-k3.1) goes through Converse.
    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    aws_region: str | None = None  # None falls back to AWS_REGION / AWS_DEFAULT_REGION
    # Read here so a .env file works outside Docker too; unset means the AWS credential
    # chain (profile, EKS Pod Identity) or AWS_BEARER_TOKEN_BEDROCK.
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    bedrock_base_url: str | None = None
    # Cheap model by default; each agent can be overridden independently.
    default_model: str = "claude-haiku-4-5"
    review_agent_model: str | None = None
    test_agent_model: str | None = None
    agent_max_tokens: int = 8000
    # Per HTTP request to the model, so a hung connection cannot stall the worker. There is
    # deliberately no cap on model calls or total run time: a capped agent on a large PR
    # stopped mid-review and returned nothing.
    agent_timeout_seconds: float = 180

    # Review size limits; they bound both token cost and comment noise.
    max_diff_chars: int = 60_000
    max_file_content_chars: int = 20_000
    max_inline_comments: int = 15

    model_prices: dict[str, ModelPrice] = DEFAULT_MODEL_PRICES

    cors_allow_origins: list[str] = []
    log_level: str = "INFO"

    def model_for(self, agent: str) -> str:
        override = {"review": self.review_agent_model, "test": self.test_agent_model}[agent]
        return override or self.default_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
