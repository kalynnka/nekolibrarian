"""Archiviste - Social media notebase tool for the Librarian.

A subordinate tool of the Librarian that manages notes and documents
in the Holovita social notebase API.
"""

import asyncio
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, TypeAdapter
from pydantic_ai import RunContext
from rich import traceback

from app.agents.deps import GroupChatDeps
from app.configs import archiviste_config

logger = logging.getLogger("archiviste")


class TokenManager:
    """Manages access and refresh tokens with automatic refresh."""

    def __init__(self):
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    def _get_headers(self) -> dict[str, str]:
        """Get common headers required by the API."""
        return {
            "X-Device-Id": archiviste_config.device_id,
            "X-Device-Name": archiviste_config.device_name,
            "X-Device-Model": archiviste_config.device_model,
            "X-Os-Name": archiviste_config.os_name,
            "X-Os-Version": archiviste_config.os_version,
            "X-App-Version": archiviste_config.app_version,
            "X-Timezone": "Asia/Shanghai",
            "Content-Type": "application/json",
        }

    async def _login(self, client: httpx.AsyncClient) -> bool:
        """Perform login to get initial tokens."""
        logger.info("Logging in to Archiviste API...")
        try:
            response = await client.post(
                f"{archiviste_config.api_base}/session",
                json={
                    "email": archiviste_config.username,
                    "password": archiviste_config.password.get_secret_value(),
                },
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            self._refresh_token = data["refresh_token"]
            self._expires_at = time.time() + data.get("expires_in", 3600) - 60
            logger.info("Successfully logged in to Archiviste API")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Login failed: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    async def _refresh(self, client: httpx.AsyncClient) -> bool:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            return False
        logger.debug("Refreshing Archiviste access token...")
        try:
            response = await client.put(
                f"{archiviste_config.api_base}/session",
                json={"refresh_token": self._refresh_token},
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            self._refresh_token = data["refresh_token"]
            self._expires_at = time.time() + data.get("expires_in", 3600) - 60
            logger.debug("Successfully refreshed access token")
            return True
        except httpx.HTTPStatusError as e:
            logger.warning(f"Token refresh failed: {e.response.status_code}")
            self._access_token = None
            self._refresh_token = None
            self._expires_at = 0
            return False
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}")
            return False

    async def get_auth_headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        """Get headers with valid authorization token. Handles login and refresh."""
        async with self._lock:
            if self._access_token and time.time() < self._expires_at:
                pass
            elif self._refresh_token:
                if not await self._refresh(client):
                    if not await self._login(client):
                        raise RuntimeError("Failed to authenticate with Archiviste API")
            else:
                if not await self._login(client):
                    raise RuntimeError("Failed to authenticate with Archiviste API")
            headers = self._get_headers()
            headers["Authorization"] = f"Bearer {self._access_token}"
            return headers


token_manager = TokenManager()
client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)


class FileInfo(BaseModel):
    """File metadata from the notebase storage."""
    id: str
    filename: str
    s3_id: str
    content_hash: str
    content_hash_md5: str
    size: int
    mimetype: str
    parent_file_id: str | None = None
    is_public: bool = False
    expires_at: str | None = None
    created_at: str | float = ""
    updated_at: str | float = ""


class ArticleInfo(BaseModel):
    """Article metadata from the notebase."""
    id: str
    title: str | None = None
    description: str | None = None
    author: str | None = None
    site_name: str | None = None
    url: str | None = None
    source: str = ""
    status: str = ""
    language: str = "en"
    published_date: str | float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] | None = None
    thumbnail_file_id: str | None = None
    content_file_id: str | None = None
    transcript_file_id: str | None = None
    thumbnail_file: FileInfo | None = None
    content_file: FileInfo | None = None
    transcript_file: FileInfo | None = None
    created_at: str | float = ""
    updated_at: str | float = ""


class TagInfo(BaseModel):
    """Tag attached to a note."""
    id: str
    name: str
    color: str


class NoteInfo(BaseModel):
    """Note information from the notebase."""
    id: str
    user_id: str | None = None
    article_id: str | None = None
    comment: str | None = None
    status: str = ""
    error_message: str | None = None
    thumbnail_file_id: str | None = None
    content_file_id: str | None = None
    thumbnail_file: FileInfo | None = None
    content_file: FileInfo | None = None
    article: ArticleInfo | None = None
    tags: list[TagInfo] = Field(default_factory=list)
    created_at: str | float = ""
    updated_at: str | float = ""

    @property
    def title(self) -> str:
        """Get the note title from article or fallback."""
        if self.article and self.article.title:
            return self.article.title
        return f"Note {self.id[:8]}"

    def get_content_file_id(self) -> str | None:
        """Get file ID for the content file (from note or article)."""
        if self.content_file:
            return self.content_file.id
        if self.article and self.article.content_file:
            return self.article.content_file.id
        return None

    def get_transcript_file_id(self) -> str | None:
        """Get file ID for the transcript file (from article)."""
        if self.article and self.article.transcript_file:
            return self.article.transcript_file.id
        return None

    def get_all_file_ids(self) -> list[str]:
        """Get all available file IDs for bulk download."""
        file_ids = []
        if self.content_file:
            file_ids.append(self.content_file.id)
        if self.article:
            if self.article.content_file:
                file_ids.append(self.article.content_file.id)
            if self.article.transcript_file:
                file_ids.append(self.article.transcript_file.id)
            if self.article.thumbnail_file:
                file_ids.append(self.article.thumbnail_file.id)
        return file_ids


class ChunkResult(BaseModel):
    """A single chunk from RAG retrieval containing markdown text."""
    id: str
    embedded_text: str
    article_id: str
    note_id: str | None = None
    file_id: str | None = None
    file: FileInfo | None = None
    created_at: str | float = ""
    updated_at: str | float = ""


class NoteSearchResult(BaseModel):
    """A single note retrieval result with relevance score (deduplicated by article)."""
    article_id: str
    note_id: str | None = None
    score: float
    note: NoteInfo | None = None

    @property
    def title(self) -> str:
        """Get title from note or article."""
        if self.note and self.note.article:
            return self.note.article.title or f"Note {self.note.id[:8]}"
        return f"Article {self.article_id[:8]}"


class SearchNotesResult(BaseModel):
    """Result from searching notes (deduplicated by article)."""
    query: str
    results: list[NoteSearchResult]


class SearchChunksResult(BaseModel):
    """Result from chunk-level retrieval (includes all matched chunks)."""
    query: str
    results: list[ChunkResult]


class CreateNoteResult(BaseModel):
    """Result from creating a note."""
    success: bool
    note: NoteInfo | None = None
    message: str = ""


class DeleteNoteResult(BaseModel):
    """Result from deleting a note."""
    success: bool
    message: str = ""


class DownloadFileResult(BaseModel):
    """Result from downloading a file from storage."""
    success: bool
    local_path: str | None = None
    file_id: str | None = None
    message: str = ""


class BulkDownloadResult(BaseModel):
    """Result from downloading multiple files."""
    results: list[DownloadFileResult]

    @property
    def successful(self) -> list[DownloadFileResult]:
        """Get all successful downloads."""
        return [r for r in self.results if r.success]

    @property
    def failed(self) -> list[DownloadFileResult]:
        """Get all failed downloads."""
        return [r for r in self.results if not r.success]


# Module-level TypeAdapters for efficient JSON parsing
_note_search_result_list_adapter: TypeAdapter[list[NoteSearchResult]] = TypeAdapter(list[NoteSearchResult])
_chunk_result_list_adapter: TypeAdapter[list[ChunkResult]] = TypeAdapter(list[ChunkResult])


async def _api_get(endpoint: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """Make an authenticated GET request and return raw response."""
    headers = await token_manager.get_auth_headers(client)
    return await client.get(
        f"{archiviste_config.api_base}{endpoint}",
        headers=headers,
        params=params,
    )


async def _api_post(endpoint: str, json_data: dict[str, Any] | None = None) -> httpx.Response:
    """Make an authenticated POST request and return raw response."""
    headers = await token_manager.get_auth_headers(client)
    return await client.post(
        f"{archiviste_config.api_base}{endpoint}",
        headers=headers,
        json=json_data,
    )


async def _api_delete(endpoint: str) -> httpx.Response:
    """Make an authenticated DELETE request and return raw response."""
    headers = await token_manager.get_auth_headers(client)
    return await client.delete(f"{archiviste_config.api_base}{endpoint}", headers=headers)


async def search_notes(
    ctx: RunContext[GroupChatDeps], query: str, limit: int = 5
) -> SearchNotesResult:
    """Search for notes in the notebase using semantic search, deduplicated by article.

    Performs hybrid RAG retrieval across all saved notes and returns results grouped
    by article. Use this when you need to find relevant saved content based on a
    topic or question, and want one result per unique source.

    For more granular chunk-level results (multiple matches from same article),
    use `retrieve_chunks` instead.

    Args:
        ctx: Run context with dependencies (injected automatically)
        query: Natural language search query. Can be a question, topic, or keywords.
               Example: "machine learning tutorials", "how to cook pasta"
        limit: Maximum number of results to return (default: 5, max: 20)

    Returns:
        SearchNotesResult containing:
        - query: The original search query
        - results: List of NoteSearchResult with article_id, note_id, score, and note details

    Example:
        >>> result = await search_notes(ctx, "python web frameworks")
        >>> for r in result.results:
        ...     print(f"{r.title} (score: {r.score:.2f})")
    """
    try:
        response = await _api_post("/retrievals", json_data={"query": query})
        response.raise_for_status()
        all_results = _note_search_result_list_adapter.validate_json(response.content)
        results = all_results[:limit]
        logger.info(f"Found {len(results)} notes for query: {query[:50]}")
        return SearchNotesResult(query=query, results=results)
    except httpx.HTTPStatusError as e:
        logger.error(f"Search failed: {e.response.status_code} - {e.response.text}")
        return SearchNotesResult(query=query, results=[])
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return SearchNotesResult(query=query, results=[])


async def retrieve_chunks(
    ctx: RunContext[GroupChatDeps], query: str, limit: int = 10
) -> SearchChunksResult:
    """Retrieve relevant text chunks from the notebase using semantic search.

    Performs hybrid RAG retrieval and returns all matched chunks ranked by relevance.
    Unlike `search_notes`, this returns multiple chunks even from the same article,
    providing more granular context for answering questions.

    This is the primary retrieval tool for question-answering workflows where you
    need specific passages rather than full articles.

    Each chunk's `embedded_text` field contains valid Markdown text. If the chunk
    contains image references in Markdown syntax (e.g.,
    `![description](/api/v1/files/{file_id}/content)`), extract the file_id from
    the URL path and download the image using `download_files`. The alt text
    (description) summarizes the main content of the picture.

    Args:
        ctx: Run context with dependencies (injected automatically)
        query: Natural language search query. Can be a question, topic, or keywords.
               More specific queries yield better results.
               Example: "what are the benefits of async programming in Python"
        limit: Maximum number of chunks to return (default: 10, max: 50)

    Returns:
        SearchChunksResult containing:
        - query: The original search query
        - results: List of ChunkResult with id, embedded_text, article_id, note_id

    Example:
        >>> result = await retrieve_chunks(ctx, "React hooks best practices")
        >>> for chunk in result.results:
        ...     print(chunk.embedded_text[:100])
    """
    try:
        response = await _api_post("/retrievals/chunks", json_data={"query": query})
        response.raise_for_status()
        all_results = _chunk_result_list_adapter.validate_json(response.content)
        results = all_results[:limit]
        logger.info(f"Retrieved {len(results)} chunks for query: {query[:50]}")
        return SearchChunksResult(query=query, results=results)
    except httpx.HTTPStatusError as e:
        logger.error(f"Chunk retrieval failed: {e.response.status_code} - {e.response.text}")
        return SearchChunksResult(query=query, results=[])
    except Exception as e:
        logger.error(f"Chunk retrieval failed: {e}")
        return SearchChunksResult(query=query, results=[])


async def get_note(ctx: RunContext[GroupChatDeps], note_id: str) -> NoteInfo | None:
    """Retrieve a specific note by its unique identifier.

    Fetches the complete note details including article metadata, tags, file info,
    and status. Use this when you have a note ID from a previous search and need
    full details including file references for downloading content.

    Args:
        ctx: Run context with dependencies (injected automatically)
        note_id: The UUID of the note to retrieve. Must be a valid UUID string.
                 Example: "019c5069-1fea-7a21-a91b-c6db74f85509"

    Returns:
        NoteInfo with complete note details including:
        - article: Full article metadata with content_file, transcript_file
        - content_file: Direct file info if note has its own content
        - tags: List of tags attached to the note

        Returns None if:
        - Note does not exist
        - Note belongs to a different user
        - Invalid note_id format

    Example:
        >>> note = await get_note(ctx, "019c5069-1fea-7a21-a91b-c6db74f85509")
        >>> if note:
        ...     print(f"Title: {note.title}, Status: {note.status}")
        ...     if s3_id := note.get_content_s3_id():
        ...         print(f"Content file: {s3_id}")
    """
    try:
        response = await _api_get(f"/notes/{note_id}")
        response.raise_for_status()
        note = NoteInfo.model_validate_json(response.content)
        logger.info(f"Retrieved note: {note_id}")
        return note
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.warning(f"Note not found: {note_id}")
        else:
            logger.error(f"Get note failed: {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Get note failed: {e}")
        return None


async def create_note_from_url(
    ctx: RunContext[GroupChatDeps],
    url: str,
    comment: str | None = None,
) -> CreateNoteResult:
    """Save a web page or video to the notebase by URL.

    Creates a new note by extracting and parsing content from the provided URL.
    The system will automatically:
    - Extract article text, title, author, and metadata from web pages
    - Download and transcribe videos (YouTube only at the moment)
    - Generate embeddings for semantic search

    Note processing happens asynchronously. The returned note will have status
    "queued" or "processing" initially. Poll with `get_note` to check completion.

    Supported content:
    - Web articles and blog posts (most sites)
    - YouTube videos (transcription via captions or speech-to-text)
    - PDF documents (via URL)

    Not yet supported:
    - Other video platforms (Vimeo, TikTok, etc.)
    - Paywalled content
    - Dynamic JavaScript-only pages

    Args:
        ctx: Run context with dependencies (injected automatically)
        url: Full URL of the web page or video to save.
             Must include protocol (https://).
             Example: "https://example.com/article" or "https://youtube.com/watch?v=..."
        comment: Optional user comment to attach to the note. Useful for adding
                 personal context or tags. Example: "Great tutorial on React hooks"

    Returns:
        CreateNoteResult containing:
        - success: True if note was created and queued
        - note: NoteInfo with ID and initial status
        - message: Human-readable result message

    Example:
        >>> result = await create_note_from_url(
        ...     ctx,
        ...     "https://blog.example.com/python-tips",
        ...     comment="Useful Python tips from conference talk"
        ... )
        >>> if result.success:
        ...     print(f"Created note {result.note.id}, status: {result.note.status}")
    """
    try:
        payload: dict[str, Any] = {"text": url}
        if comment:
            payload["comment"] = comment
        response = await _api_post("/notes/text", json_data=payload)
        response.raise_for_status()
        note = NoteInfo.model_validate_json(response.content)
        logger.info(f"Created note: {note.id} - {note.title}")
        return CreateNoteResult(
            success=True,
            note=note,
            message=f"Note created successfully: {note.title}",
        )
    except httpx.HTTPStatusError as e:
        error_msg = f"Create note failed: {e.response.status_code}"
        logger.error(f"{error_msg} - {e.response.text}")
        return CreateNoteResult(success=False, message=error_msg)
    except Exception as e:
        error_msg = f"Create note failed: {e}"
        logger.error(error_msg)
        return CreateNoteResult(success=False, message=error_msg)


async def delete_note(ctx: RunContext[GroupChatDeps], note_id: str) -> DeleteNoteResult:
    """Permanently delete a note from the notebase.

    Removes the note and its associated data. This action cannot be undone.
    The underlying article may still exist if referenced by other notes.

    Args:
        ctx: Run context with dependencies (injected automatically)
        note_id: The UUID of the note to delete.
                 Example: "019c5069-1fea-7a21-a91b-c6db74f85509"

    Returns:
        DeleteNoteResult containing:
        - success: True if note was deleted
        - message: Human-readable result or error message

    Example:
        >>> result = await delete_note(ctx, "019c5069-1fea-7a21-a91b-c6db74f85509")
        >>> print(result.message)  # "Note ... deleted successfully" or error
    """
    try:
        response = await _api_delete(f"/notes/{note_id}")
        response.raise_for_status()
        logger.info(f"Deleted note: {note_id}")
        return DeleteNoteResult(success=True, message=f"Note {note_id} deleted successfully")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return DeleteNoteResult(success=False, message=f"Note not found: {note_id}")
        error_msg = f"Delete note failed: {e.response.status_code}"
        logger.error(f"{error_msg} - {e.response.text}")
        return DeleteNoteResult(success=False, message=error_msg)
    except Exception as e:
        error_msg = f"Delete note failed: {e}"
        logger.error(error_msg)
        return DeleteNoteResult(success=False, message=error_msg)


async def download_files(
    ctx: RunContext[GroupChatDeps],
    file_ids: list[str],
) -> BulkDownloadResult:
    """Download multiple files from the notebase in parallel.

    Downloads files using their UUIDs with parallel network I/O for efficiency.
    Files are cached locally to avoid re-downloading.

    Args:
        ctx: Run context with dependencies (injected automatically)
        file_ids: List of file UUIDs to download.

    Returns:
        BulkDownloadResult containing:
        - results: List of DownloadFileResult for each file
        - successful: Property to get successful downloads
        - failed: Property to get failed downloads

    Example:
        >>> note = await get_note(ctx, note_id)
        >>> file_ids = [f.id for f in [note.content_file, note.article.content_file] if f]
        >>> bulk_result = await download_files(ctx, file_ids)
        >>> for result in bulk_result.successful:
        ...     print(f"Downloaded: {result.local_path}")
    """
    try:
        tasks = [_download_single_file(file_id) for file_id in file_ids]
        results = await asyncio.gather(*tasks)
    except BaseException as e:
        # Handle ExceptionGroups from TaskGroup and other errors
        if isinstance(e, BaseExceptionGroup):
            logger.error(f"ExceptionGroup in agent: {type(e).__name__}")
            for exc in e.exceptions:
                logger.error(f"  - {type(exc).__name__}: {exc}")
        else:
            logger.error(f"Agent error: {type(e).__name__}: {e}")
        return BulkDownloadResult(results=[])

    return BulkDownloadResult(results=list(results))


async def _download_single_file(file_id: str) -> DownloadFileResult:
    """Internal function to download a single file via API."""
    try:
        # Ensure cache directory exists
        archiviste_config.cache_dir.mkdir(parents=True, exist_ok=True)

        # Check cache first - look for files with this file_id prefix
        prefix = f"{file_id}."
        for existing in archiviste_config.cache_dir.iterdir():
            if existing.name.startswith(prefix):
                logger.debug(f"File cache hit: {existing}")
                return DownloadFileResult(
                    success=True,
                    local_path=str(existing.absolute()),
                    file_id=file_id,
                    message="File retrieved from cache",
                )

        # Download via API
        logger.info(f"Downloading file: {file_id}")
        headers = await token_manager.get_auth_headers(client)
        response = await client.get(
            f"{archiviste_config.api_base}/files/{file_id}/content",
            headers=headers,
        )
        response.raise_for_status()

        # Get extension from Content-Type header (e.g., "image/jpeg" -> ".jpg")
        content_type = response.headers.get("content-type", "application/octet-stream")
        content_type = content_type.split(";")[0].strip()
        ext = mimetypes.guess_extension(content_type) or ""
        cache_path = archiviste_config.cache_dir / f"{file_id}{ext}"

        # Write to cache
        cache_path.write_bytes(response.content)
        logger.info(f"Downloaded file to: {cache_path}")

        return DownloadFileResult(
            success=True,
            local_path=str(cache_path.absolute()),
            file_id=file_id,
            message=f"File downloaded successfully ({len(response.content)} bytes)",
        )

    except httpx.HTTPStatusError as e:
        error_msg = f"Download failed: {e.response.status_code}"
        logger.error(f"{error_msg} for {file_id}")
        return DownloadFileResult(success=False, file_id=file_id, message=error_msg)
    except Exception as e:
        error_msg = f"Download failed: {e}"
        logger.error(error_msg)
        return DownloadFileResult(success=False, file_id=file_id, message=error_msg)
