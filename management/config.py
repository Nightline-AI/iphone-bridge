"""Configuration for Management Agent."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Management agent settings."""

    # Authentication
    management_token: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8081

    # Paths
    install_dir: Path = Path.home() / "iphone-bridge"
    log_dir: Path = Path("/var/log/iphone-bridge")

    # Bridge info (read from shared .env)
    nightline_client_id: str = ""
    
    # Display name for the bridge (shown in dashboard header)
    bridge_display_name: str = "iPhone Bridge"

    # Cookie settings
    cookie_name: str = "mgmt_session"
    cookie_max_age: int = 60 * 60 * 24 * 30  # 30 days

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def env_file_path(self) -> Path:
        return self.install_dir / ".env"

    @property
    def tunnel_url(self) -> str | None:
        if self.nightline_client_id:
            return f"https://bridge-{self.nightline_client_id}.nightline.app"
        return None

    @property
    def management_url(self) -> str | None:
        if self.nightline_client_id:
            return f"https://manage-{self.nightline_client_id}.nightline.app"
        return None


settings = Settings()
