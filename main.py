from collections import defaultdict, deque
from functools import lru_cache
from typing import Any, DefaultDict, Deque, Dict, List

from ncatbot.core import BotClient, GroupMessageEvent, PrivateMessage
from pydantic_ai import ModelMessage

from app import agents
from app.collector import MessageBatchHandler

bot = BotClient()


# Store a batcher for each user
private_handlers: Dict[int, MessageBatchHandler[PrivateMessage, Any]] = {}
group_handlers: Dict[int, MessageBatchHandler[GroupMessageEvent, Any]] = {}

in_memory_memory: DefaultDict[int, Deque[list[ModelMessage]]] = defaultdict(
    lambda: deque(maxlen=5)
)


@lru_cache(maxsize=32)
def get_private_batcher(
    user_id: int | str,
) -> MessageBatchHandler[PrivateMessage, None]:
    """Get or create a batcher for a specific user"""
    if user_id not in private_handlers:

        async def handle_batch(messages: List[PrivateMessage]) -> None:
            await bot.api.set_input_status(user_id=user_id, event_type=1)
            memories = in_memory_memory[int(user_id)]
            result = await agents.private_chat_agent.run(
                user_prompt="\n".join([msg.raw_message for msg in messages]),
                message_history=[msg for round in memories for msg in round],
            )
            memories.append(result.new_messages())
            for msg in result.output:
                if msg.strip():
                    await bot.api.post_private_msg(
                        user_id=user_id,
                        text=msg,
                    )

        private_handlers[int(user_id)] = MessageBatchHandler(
            handler=handle_batch,
            batch_delay=0.5,
        )

    return private_handlers[int(user_id)]


@lru_cache(maxsize=32)
def get_group_batcher(
    group_id: int | str,
) -> MessageBatchHandler[GroupMessageEvent, Any]:
    """Get or create a batcher for a specific group"""
    if group_id not in group_handlers:

        async def handle_batch(messages: List[GroupMessageEvent]) -> None:
            memories = in_memory_memory[int(group_id)]
            result = await agents.group_chat_agent.run(
                user_prompt="\n".join([msg.raw_message for msg in messages])
            )
            memories.append(result.new_messages())
            for msg in result.output:
                await bot.api.post_group_msg(
                    group_id=group_id,
                    text=msg,
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
