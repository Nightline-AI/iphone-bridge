"""Configuration settings for iPhone Bridge."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Nightline server to forward messages to
    nightline_server_url: str = "http://localhost:8000"

    # Shared secret for webhook authentication
    webhook_secret: str = "change-me-in-production"

    # Polling interval for chat.db (seconds)
    poll_interval: float = 2.0

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080

    # Logging level
    log_level: str = "INFO"

    # Whether to process messages from before startup
    process_historical: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
