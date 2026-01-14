from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class PixivConfig(BaseSettings):
    """Pixiv API configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PIXIV_",
        extra="ignore",
    )

    refresh_token: str = ""
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

__all__ = [
    "PixivConfig",
    "NcatBotConfig",
    "QWeatherConfig",
    "config",
    "pixiv_config",
    "qweather_config",
]
