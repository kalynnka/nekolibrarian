from functools import lru_cache
from typing import Any, Dict, List

from ncatbot.core import BotClient, GroupMessageEvent, PrivateMessage

from app import agents
from app.collector import MessageBatchHandler

bot = BotClient()

# Store a batcher for each user
private_handlers: Dict[int, MessageBatchHandler[PrivateMessage, Any]] = {}
group_handlers: Dict[int, MessageBatchHandler[GroupMessageEvent, Any]] = {}


@lru_cache(maxsize=32)
def get_private_batcher(
    user_id: int | str,
) -> MessageBatchHandler[PrivateMessage, None]:
    """Get or create a batcher for a specific user"""
    if user_id not in private_handlers:

        async def handle_batch(messages: List[PrivateMessage]) -> None:
            result = await agents.chat.run(
                user_prompt="\n".join([msg.raw_message for msg in messages])
            )
            await bot.api.post_private_msg(
                user_id=user_id,
                text=result.output,
            )

        private_handlers[int(user_id)] = MessageBatchHandler(
            handler=handle_batch,
            batch_delay=1,
        )

    return private_handlers[int(user_id)]


@lru_cache(maxsize=32)
def get_group_batcher(
    group_id: int | str,
) -> MessageBatchHandler[GroupMessageEvent, Any]:
    """Get or create a batcher for a specific group"""
    if group_id not in group_handlers:

        async def handle_batch(messages: List[GroupMessageEvent]) -> None:
            result = await agents.chat.run(
                user_prompt="\n".join([msg.raw_message for msg in messages])
            )
            await bot.api.post_group_msg(
                group_id=group_id,
                text=result.output,
            )

        group_handlers[int(group_id)] = MessageBatchHandler(
            handler=handle_batch,
            batch_delay=1,
        )

    return group_handlers[int(group_id)]


@bot.on_private_message()  # pyright: ignore[reportArgumentType]
async def handle_private_message(msg: PrivateMessage):
    await get_private_batcher(msg.user_id).push(msg)


@bot.on_group_message()  # pyright: ignore[reportArgumentType]
async def handle_group_message(msg: GroupMessageEvent):
    await get_group_batcher(msg.group_id).push(msg)


if __name__ == "__main__":
    bot.run()
