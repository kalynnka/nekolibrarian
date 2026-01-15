"""QWeather API tool for weather forecasts using JWT authentication."""

import base64
import json
import logging
import time
from typing import Literal

import httpx
from cryptography.hazmat.primitives import serialization
from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agents.deps import GroupChatDeps
from app.configs import qweather_config

logger = logging.getLogger("qweather")

# Global httpx client - created once, reused for all requests
client = httpx.AsyncClient(
    timeout=30.0,
    follow_redirects=True,
    headers={"Accept-Encoding": "gzip"},
)


def _generate_jwt() -> str:
    """Generate JWT token for QWeather API authentication using Ed25519."""
    private_key_pem = qweather_config.private_key_path.read_text()
    iat = int(time.time()) - 30  # 30s before to handle time drift

    # Build JWT manually to avoid PyJWT adding 'typ' header
    def b64url_encode(data: dict) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode())
            .rstrip(b"=")
            .decode()
        )

    header = {"alg": "EdDSA", "kid": qweather_config.key_id}
    payload = {"sub": qweather_config.project_id, "iat": iat, "exp": iat + 900}
    signing_input = f"{b64url_encode(header)}.{b64url_encode(payload)}"

    # Sign with Ed25519
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None
    )
    # Ed25519 sign() takes no algorithm parameter (it's implicit)
    signature = private_key.sign(signing_input.encode())  # type: ignore[call-arg]
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    return f"{signing_input}.{signature_b64}"


class WeatherDaily(BaseModel):
    """Daily weather forecast data."""

    fx_date: str
    temp_max: str
    temp_min: str
    text_day: str
    text_night: str
    wind_dir_day: str
    wind_scale_day: str
    humidity: str
    precip: str
    sunrise: str | None = None
    sunset: str | None = None


class WeatherForecastResult(BaseModel):
    """Weather forecast result."""

    location: str
    update_time: str
    daily: list[WeatherDaily]


async def get_weather_forecast(
    location: str | None = None,
    days: Literal["3d", "7d"] = "3d",
) -> WeatherForecastResult:
    """
    Get daily weather forecast from QWeather API.

    Args:
        location: Location ID or coordinates (lon,lat). Default is Shanghai.
        days: Forecast days (3d or 7d)

    Returns:
        WeatherForecastResult with forecast data
    """
    if not qweather_config.key_id or not qweather_config.project_id:
        raise ValueError("QWeather API credentials not configured")

    location = location or qweather_config.default_location
    response = await client.get(
        f"https://{qweather_config.api_host}/v7/weather/{days}",
        params={"location": location, "lang": "zh", "unit": "m"},
        headers={"Authorization": f"Bearer {_generate_jwt()}"},
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "200":
        raise ValueError(f"QWeather API error: {data.get('code')}")

    return WeatherForecastResult(
        location=location,
        update_time=data.get("updateTime", ""),
        daily=[
            WeatherDaily(
                fx_date=d.get("fxDate", ""),
                temp_max=d.get("tempMax", ""),
                temp_min=d.get("tempMin", ""),
                text_day=d.get("textDay", ""),
                text_night=d.get("textNight", ""),
                wind_dir_day=d.get("windDirDay", ""),
                wind_scale_day=d.get("windScaleDay", ""),
                humidity=d.get("humidity", ""),
                precip=d.get("precip", ""),
                sunrise=d.get("sunrise"),
                sunset=d.get("sunset"),
            )
            for d in data.get("daily", [])
        ],
    )


def _format_forecast(forecast: WeatherForecastResult) -> str:
    """Format weather forecast into a readable message."""
    location_name = (
        "上海"
        if forecast.location == qweather_config.default_location
        else forecast.location
    )
    lines = [f"📍 {location_name}天气预报"]

    for day in forecast.daily:
        _, month, date = day.fx_date.split("-")
        parts = [
            f"\n🗓️ {month}月{date}日",
            f"🌡️ {day.temp_min}°C ~ {day.temp_max}°C",
            f"☀️ 白天: {day.text_day}  🌙 夜间: {day.text_night}",
            f"💧 湿度: {day.humidity}%  🌬️ {day.wind_dir_day}{day.wind_scale_day}级",
        ]
        if day.precip and float(day.precip) > 0:
            parts.append(f"🌧️ 降水: {day.precip}mm")
        if day.sunrise and day.sunset:
            parts.append(f"🌅 {day.sunrise} - 🌇 {day.sunset}")
        lines.append("\n".join(parts))

    return "\n".join(lines)


async def get_weather(
    ctx: RunContext[GroupChatDeps],
    location: str | None = None,
    days: Literal["3d", "7d"] = "3d",
) -> str:
    """
    Get weather forecast for a location.

    This tool fetches weather forecast from QWeather API and returns a formatted message.
    Default location is Shanghai if not specified.

    Args:
        ctx: Run context from pydantic-ai
        location: Location ID or coordinates. Default is Shanghai if not specified.
        days: Forecast days, either "3d" or "7d"

    Returns:
        Formatted weather forecast message
    """
    try:
        forecast = await get_weather_forecast(location=location, days=days)
        return _format_forecast(forecast)
    except Exception as e:
        logger.error(f"Failed to get weather: {e}")
        return f"抱歉，获取天气信息失败: {e}"
