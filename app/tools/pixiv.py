import asyncio
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Literal, ParamSpec, TypeVar

from pixivpy_async import AppPixivAPI, PixivClient
from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agents.deps import GroupChatDeps
from app.configs import pixiv_config

logger = logging.getLogger("pixiv")

P = ParamSpec("P")
R = TypeVar("R")

TOKEN_REFRESH_INTERVAL = 15 * 60  # 15 minutes in seconds


class PixivTokenManager:
    """Manages Pixiv API authentication with automatic token refresh."""

    def __init__(self) -> None:
        self.client: PixivClient | None = None
        self.api = AppPixivAPI()
        self._last_login: float = 0
        self._lock = asyncio.Lock()

    def _needs_refresh(self) -> bool:
        """Check if token needs refresh (every 15 minutes)."""
        return time.time() - self._last_login > TOKEN_REFRESH_INTERVAL

    async def ensure_auth(self) -> None:
        """Ensure API is authenticated, refreshing if needed."""
        async with self._lock:
            if self._needs_refresh():
                await self.login()

    async def login(self) -> None:
        """Perform login to refresh token."""
        logger.info("Refreshing Pixiv token...")
        try:
            if self.client is None:
                self.client = PixivClient()
                self.api.session = self.client.start()
            await self.api.login(
                refresh_token=pixiv_config.refresh_token.get_secret_value()
            )
            self._last_login = time.time()
            logger.info("Pixiv token refreshed successfully")
        except Exception as e:
            logger.error(f"Pixiv login failed: {e}")
            raise

    async def refresh_and_retry(self) -> None:
        """Force refresh token (used after API failure)."""
        async with self._lock:
            self._last_login = 0  # Force refresh
            await self.login()

    async def close(self) -> None:
        """Close the Pixiv client session."""
        if self.client is not None:
            await self.client.close()
            self.client = None
            logger.info("Pixiv client session closed")


token_manager = PixivTokenManager()
api = token_manager.api
client = token_manager.client  # Expose client for cleanup


def with_auto_refresh(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Decorator that ensures auth and retries once on failure."""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        await token_manager.ensure_auth()
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Pixiv API call failed, retrying after refresh: {e}")
            await token_manager.refresh_and_retry()
            return await func(*args, **kwargs)

    return wrapper


class PixivImageUrls(BaseModel):
    """URLs for different sizes of a Pixiv illustration."""

    large: str | None = None
    medium: str | None = None
    square_medium: str | None = None


class PixivIllust(BaseModel):
    """Pixiv illustration metadata."""

    id: int
    title: str
    author: str
    author_id: int
    tags: list[str]
    image_urls: PixivImageUrls
    local_path: Annotated[str, Path] | None = None


class PixivSearchResult(BaseModel):
    """Result from Pixiv search or ranking."""

    query: str
    illusts: list[PixivIllust]


async def download_image(image_url: str) -> str | None:
    """
    Download image from Pixiv with local caching.

    Args:
        image_url: The Pixiv image URL to download

    Returns:
        Path to the local image file as string, or None if download failed
    """
    # Extract filename from URL (e.g., 12345678_p0.jpg)
    cache_path = pixiv_config.image_dir / image_url.split("/")[-1]

    # Check cache first
    if cache_path.exists():
        logger.debug(f"Image cache hit: {cache_path}")
        return str(cache_path)

    # Ensure directory exists
    pixiv_config.image_dir.mkdir(parents=True, exist_ok=True)

    try:
        await token_manager.api.download(
            image_url,
            path=str(pixiv_config.image_dir),
            name=cache_path.name,
        )
        logger.info(f"Downloaded image: {cache_path}")
        return str(cache_path)
    except Exception as e:
        logger.warning(f"Failed to download image {image_url}: {e}")
        return None


@with_auto_refresh
async def search_illustrations(
    ctx: RunContext[GroupChatDeps], keyword: str, limit: int = 3
) -> PixivSearchResult:
    """
    Search illustrations on Pixiv by keyword/tag.
    Use this when users ask for anime illustrations, artwork, or images by specific tags.

    Args:
        keyword: The search keyword or tag (can be Japanese or English)
        limit: Maximum number of results to return (default 3, max from config)

    Returns:
        PixivSearchResult containing illustration metadata and local file paths
    """
    result = await token_manager.api.search_illust(keyword, search_target="partial_match_for_tags")

    if not result.illusts:
        return PixivSearchResult(query=keyword, illusts=[])

    illusts = result.illusts[: min(limit, pixiv_config.search_limit)]

    # Download images in parallel
    image_urls = [illust.image_urls.medium for illust in illusts]
    download_tasks = [download_image(url) for url in image_urls]
    downloaded_paths = await asyncio.gather(*download_tasks)

    output = []
    for illust, local_path in zip(illusts, downloaded_paths):
        output.append(
            PixivIllust(
                id=illust.id,
                title=illust.title,
                author=illust.user.name,
                author_id=illust.user.id,
                tags=[tag.name for tag in illust.tags[:5]],
                image_urls=PixivImageUrls(
                    large=illust.image_urls.large,
                    medium=illust.image_urls.medium,
                    square_medium=illust.image_urls.square_medium,
                ),
                local_path=local_path,
            )
        )

    return PixivSearchResult(query=keyword, illusts=output)


@with_auto_refresh
async def daily_ranking(
    ctx: RunContext[GroupChatDeps],
    mode: Literal["day", "week", "month", "day_male", "day_female", "day_r18"] = "day",
    limit: int = 5,
) -> PixivSearchResult:
    """
    Get Pixiv illustration rankings.
    Use this when users ask for popular/trending illustrations or daily rankings.

    Args:
        mode: Ranking mode - 'day' (daily), 'week' (weekly), 'month' (monthly),
              'day_male' (daily male), 'day_female' (daily female), 'day_r18' (R18 daily)
        limit: Maximum number of results to return (default 5, max from config)

    Returns:
        PixivSearchResult containing ranked illustration metadata and local file paths
    """
    mode_names = {
        "day": "日榜",
        "week": "周榜",
        "month": "月榜",
        "day_male": "男性向日榜",
        "day_female": "女性向日榜",
        "day_r18": "R18日榜",
    }

    result = await token_manager.api.illust_ranking(mode)

    if not result.illusts:
        return PixivSearchResult(query=mode_names.get(mode, mode), illusts=[])

    illusts = result.illusts[: min(limit, pixiv_config.ranking_limit)]

    # Download images in parallel
    image_urls = [illust.image_urls.medium for illust in illusts]
    download_tasks = [download_image(url) for url in image_urls]
    downloaded_paths = await asyncio.gather(*download_tasks)

    output = []
    for illust, local_path in zip(illusts, downloaded_paths):
        output.append(
            PixivIllust(
                id=illust.id,
                title=illust.title,
                author=illust.user.name,
                author_id=illust.user.id,
                tags=[tag.name for tag in illust.tags[:5]],
                image_urls=PixivImageUrls(
                    large=illust.image_urls.large,
                    medium=illust.image_urls.medium,
                    square_medium=illust.image_urls.square_medium,
                ),
                local_path=local_path,
            )
        )

    return PixivSearchResult(query=mode_names.get(mode, mode), illusts=output)
