from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PixivConfig(BaseSettings):
    """Pixiv API configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PIXIV_",
        extra="ignore",
    )

    refresh_token: SecretStr = SecretStr("")
    search_limit: int = 3
    ranking_limit: int = 5
    image_dir: Path = Path("./pixiv/images")


class QWeatherConfig(BaseSettings):
    """QWeather API configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QWEATHER_",
        extra="ignore",
    )

    api_host: str = "devapi.qweather.com"
    key_id: str = ""  # Credential ID (kid)
    project_id: str = ""  # Project ID (sub)
    private_key_path: Path = Path("./qweather/ed25519-private.pem")
    default_location: str = "101020100"  # Shanghai


class ArchivisteConfig(BaseSettings):
    """Archiviste (social media notebase) API configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ARCHIVISTE_",
        extra="ignore",
    )

    # API base URL
    base_url: str = "http://host.docker.internal:5002"
    api_version: str = "v1"

    # Authentication credentials
    username: str = "test@holovita.ai"
    password: SecretStr = SecretStr("Password123!")

    # Device headers (required by API)
    device_id: str = "7608e47d-a8f5-4f43-9c9f-534783b2ccfb"
    device_name: str = "Archiviste Bot"
    device_model: str = "Bot/1.0"
    os_name: str = "Linux"
    os_version: str = "1.0"
    app_version: str = "1.0.0"

    @property
    def api_base(self) -> str:
        """Full API base URL."""
        return f"{self.base_url}/api/{self.api_version}"

    # Local cache directory for downloaded files
    cache_dir: Path = Path("./archiviste/files")


class NcatBotConfig(BaseSettings):
    """Main application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    postgres_dsn: Annotated[str, PostgresDsn] = (
        r"postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
    )

    # Batch handler settings
    batch_handler_lru_size: int = 32

    # In-memory message history length
    memory_groups_count: int = 16


# Module-level singletons
config = NcatBotConfig()
pixiv_config = PixivConfig()
qweather_config = QWeatherConfig()
archiviste_config = ArchivisteConfig()

__all__ = [
    "ArchivisteConfig",
    "PixivConfig",
    "NcatBotConfig",
    "QWeatherConfig",
    "archiviste_config",
    "config",
    "pixiv_config",
    "qweather_config",
]
