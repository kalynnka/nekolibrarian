import asyncio
import logging
from pathlib import Path
from typing import Literal, Optional

from pixivpy_async import AppPixivAPI, PixivClient
from pydantic import BaseModel
from pydantic_ai import RunContext

from app.configs import pixiv_config

logger = logging.getLogger("pixiv")


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
    local_path: Path | None = None


class PixivSearchResult(BaseModel):
    """Result from Pixiv search or ranking."""

    query: str
    illusts: list[PixivIllust]


api = AppPixivAPI()

global client
client: Optional[PixivClient] = None


async def login():
    client = PixivClient()
    api.session = client.start()
    return await api.login(refresh_token=pixiv_config.refresh_token)


async def download_image(image_url: str) -> Path | None:
    """
    Download image from Pixiv with local caching.

    Args:
        image_url: The Pixiv image URL to download

    Returns:
        Path to the local image file, or None if download failed
    """
    # Extract filename from URL (e.g., 12345678_p0.jpg)
    cache_path = pixiv_config.image_dir / image_url.split("/")[-1]

    # Check cache first
    if cache_path.exists():
        logger.debug(f"Image cache hit: {cache_path}")
        return cache_path

    # Ensure directory exists
    pixiv_config.image_dir.mkdir(parents=True, exist_ok=True)

    try:
        await api.download(
            image_url,
            path=str(pixiv_config.image_dir),
            name=cache_path.name,
        )
        logger.info(f"Downloaded image: {cache_path}")
        return cache_path
    except Exception as e:
        logger.warning(f"Failed to download image {image_url}: {e}")
        return None


async def search_illustrations(
    ctx: RunContext[None], keyword: str, limit: int = 3
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
    result = await api.search_illust(keyword, search_target="partial_match_for_tags")

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


async def daily_ranking(
    ctx: RunContext[None],
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

    result = await api.illust_ranking(mode)

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
