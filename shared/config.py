from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Attempts per message before it is moved to the dead letter topic.
    worker_max_attempts: int = 3

    github_webhook_secret: str = ""
    cors_allow_origins: list[str] = []
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
