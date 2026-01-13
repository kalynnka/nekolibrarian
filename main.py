from collections import defaultdict, deque
from functools import lru_cache
from logging import warning
from typing import DefaultDict, Deque, Dict, List

from ncatbot.core import BotClient, GroupMessageEvent, PrivateMessage
from pydantic_ai.messages import ModelMessage

from app import agents
from app.collector import MessageBatchHandler

bot = BotClient()


# Store a batcher for each user
private_handlers: Dict[int, MessageBatchHandler[PrivateMessage, None]] = {}
group_handlers: Dict[int, MessageBatchHandler[GroupMessageEvent, str]] = {}

# TODO: persist chat memory to PG
in_memory_memory: DefaultDict[int, Deque[list[ModelMessage]]] = defaultdict(
    lambda: deque(maxlen=10)
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
            result = await agents.private.chat_agent.run(
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
) -> MessageBatchHandler[GroupMessageEvent, str]:
    """Get or create a batcher for a specific group"""
    if group_id not in group_handlers:

        async def handle_batch(messages: List[GroupMessageEvent]):
            memories = in_memory_memory[int(group_id)]
            result = await agents.group.chat_agent.run(
                user_prompt="\n".join(
                    [
                        f"{msg.sender.card or 'anonymous'}: {msg.raw_message}"
                        for msg in messages
                    ]
                )
            )
            memories.append(result.new_messages())
            return result.output

        group_handlers[int(group_id)] = MessageBatchHandler(
            handler=handle_batch,
            batch_delay=1,
        )

    return group_handlers[int(group_id)]


def is_group_at(event) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    bot_id = event.self_id
    for message_spiece in event.message.messages:
        if (
            message_spiece.msg_seg_type == "at"
            and getattr(message_spiece, "qq", None) == bot_id
        ):
            return True
    return False


@bot.on_private_message()  # pyright: ignore[reportArgumentType]
async def handle_private_message(msg: PrivateMessage):
    get_private_batcher(msg.user_id).push(msg)


@bot.on_group_message()  # pyright: ignore[reportArgumentType]
async def handle_group_message(msg: GroupMessageEvent):
    batch_handler = get_group_batcher(msg.group_id)
    batch_handler.push(msg, handle=False)
    if is_group_at(msg):
        reply = await batch_handler.consume()
        if not (reply := reply.strip()):
            warning(f"Empty reply generated for group at message: {msg.raw_message}.")
            return
        await bot.api.post_group_msg(
            group_id=msg.group_id,
            text=reply,
            reply=msg.message_id,
        )


if __name__ == "__main__":
    bot.run()
