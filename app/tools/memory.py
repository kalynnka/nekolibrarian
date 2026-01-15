"""Memory persistence and loading utilities for model messages."""

import datetime
import logging
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext
from sqlalchemy import select

from app.agents.deps import GroupChatDeps
from app.database import async_session_factory
from app.schemas import Message, ModelMessage, _now_shanghai

logger = logging.getLogger("memory")

# Maximum time range for message retrieval (1 day)
MAX_TIME_RANGE = datetime.timedelta(days=1)
# Default time range (30 minutes)
DEFAULT_TIME_RANGE = datetime.timedelta(minutes=30)


class ChatHistory(BaseModel):
    """Result of loading chat messages."""

    model_config = ConfigDict(from_attributes=True)

    messages: list[Message]
    start_time: datetime.datetime
    end_time: datetime.datetime
    count: int


async def load_recent_messages(
    user_id: int | None = None,
    group_id: int | None = None,
    start_time: datetime.datetime | None = None,
    end_time: datetime.datetime | None = None,
) -> ChatHistory:
    """
    Load recent chat messages from database.

    Args:
        user_id: The user ID to filter by (for private chats)
        group_id: The group ID to filter by (for group chats)
        start_time: Start of time range (default: 30 minutes before now)
        end_time: End of time range (default: now)

    Returns:
        ChatHistory containing messages and metadata

    Note:
        - If group_id is provided, filters by group_id (group chat)
        - If group_id is None, filters by user_id and group_id IS NULL (private chat)
    """
    if user_id is None and group_id is None:
        raise ValueError("Either user_id or group_id must be provided")

    now = _now_shanghai()

    # Set defaults
    if end_time is None:
        end_time = now
    if start_time is None:
        start_time = end_time - DEFAULT_TIME_RANGE

    # Clamp time range to maximum 1 day
    if end_time - start_time > MAX_TIME_RANGE:
        start_time = end_time - MAX_TIME_RANGE

    async with async_session_factory() as session:
        # Build query based on chat type
        if group_id is not None:
            # Group chat: filter by group_id
            stmt = (
                select(Message)
                .where(
                    Message["group_id"] == group_id,
                    Message["timestamp"] >= start_time,
                    Message["timestamp"] <= end_time,
                )
                .order_by(Message["timestamp"].asc())
            )
        else:
            # Private chat: filter by user_id and group_id IS NULL
            stmt = (
                select(Message)
                .where(
                    Message["user_id"] == user_id,
                    Message["group_id"].is_(None),
                    Message["timestamp"] >= start_time,
                    Message["timestamp"] <= end_time,
                )
                .order_by(Message["timestamp"].asc())
            )

        result = await session.execute(stmt)
        messages = result.scalars().all()

        return ChatHistory(
            messages=list(messages),
            start_time=start_time,
            end_time=end_time,
            count=len(messages),
        )


async def get_recent_chat_history(
    ctx: RunContext[GroupChatDeps],
    minutes_ago: int = 30,
) -> str:
    """
    Get recent chat history for reference or summary.

    This tool retrieves recent messages from the current chat.
    Use this when users ask about previous conversations, want a summary,
    or need context about what was discussed earlier.

    Args:
        ctx: Run context from pydantic-ai (contains user_id and group_id in deps)
        minutes_ago: How many minutes of history to retrieve (1-1440, default 30)

    Returns:
        Formatted chat history as text
    """
    # Get user_id and group_id from context dependencies
    user_id = ctx.deps.user_id
    group_id = ctx.deps.group_id

    # Validate that at least one ID is provided
    if user_id is None and group_id is None:
        return "错误: 无法获取聊天信息"

    # Clamp minutes to valid range (1 minute to 1 day)
    minutes_ago = max(1, min(minutes_ago, 1440))

    now = _now_shanghai()
    start_time = now - datetime.timedelta(minutes=minutes_ago)

    chat_type = "群聊" if group_id else "私聊"

    try:
        history = await load_recent_messages(
            user_id=user_id,
            group_id=group_id,
            start_time=start_time,
            end_time=now,
        )

        if not history.messages:
            return f"最近{minutes_ago}分钟内没有{chat_type}记录"

        lines = [f"最近{minutes_ago}分钟的{chat_type}记录 ({history.count}条):"]
        for msg in history.messages:
            time_str = msg.timestamp.strftime("%H:%M")
            lines.append(f"[{time_str}] {msg.content}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Failed to load chat history: {e}")
        return f"获取聊天记录失败: {e}"


async def persist_model_messages(messages: Sequence[ModelMessage]):
    """Persist a sequence of ModelMessage to the database asynchronously.

    Note: Must be called within a `with sqlalchemy_materia:` context.
    """
    async with async_session_factory() as session:
        session.add_all(messages)
        await session.commit()
