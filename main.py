import logging
import pickle
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import DefaultDict, Deque, Dict, List

from ncatbot.core import BotClient, GroupMessageEvent, MetaEvent, PrivateMessage
from ncatbot.core.event.message_segment import MessageArray
from pydantic_ai import ModelRequest
from pydantic_ai.messages import ModelMessage

from app import agents
from app.collector import MessageBatchHandler
from app.tools import pixiv

logger = logging.getLogger("NekoLibrarian")
bot = BotClient()


# Store a batcher for each user
private_handlers: Dict[int, MessageBatchHandler[PrivateMessage, None]] = {}
group_handlers: Dict[int, MessageBatchHandler[GroupMessageEvent, list]] = {}

# TODO: persist chat memory to PG
MEMORY_FILE = Path("./data/chat_memory.pkl")
in_memory_memory: DefaultDict[int, Deque[ModelMessage]] = defaultdict(
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
                message_history=memories,
            )
            memories.extend(result.new_messages())
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
) -> MessageBatchHandler[GroupMessageEvent, list]:
    """Get or create a batcher for a specific group""" ""
    if group_id not in group_handlers:

        async def handle_batch(messages: List[GroupMessageEvent]):
            memories = in_memory_memory[int(group_id)]
            last = messages.pop()
            memories.extend(
                (
                    ModelRequest.user_text_prompt(
                        "".join(
                            f"{event.sender.card or event.sender.nickname or 'anonymous'}: {seg.text}"
                            for seg in event.message.filter_text()
                        )
                    )
                    for event in messages
                )
            )
            result = await agents.group.chat_agent.run(
                user_prompt=f"{last.sender.card or last.sender.nickname or 'anonymous'}: {last.raw_message}",
                message_history=memories,
            )
            memories.extend(result.new_messages())
            return result.output

        group_handlers[int(group_id)] = MessageBatchHandler(
            handler=handle_batch,
            batch_delay=1,
        )

    return group_handlers[int(group_id)]


@bot.on_private_message()  # pyright: ignore[reportArgumentType]
async def handle_private_message(msg: PrivateMessage):
    get_private_batcher(msg.user_id).push(msg)


@bot.on_group_message()  # pyright: ignore[reportArgumentType]
async def handle_group_message(event: GroupMessageEvent):
    batch_handler = get_group_batcher(event.group_id)
    batch_handler.push(event, handle=False)
    if event.message.is_user_at(user_id=event.self_id):
        segments = await batch_handler.consume()
        if not segments:
            logger.warning(
                f"Empty reply generated for group at message: {event.raw_message}."
            )
            return

        # Convert agent output to MessageArray
        msg_array = MessageArray([seg.to_message_segment() for seg in segments])

        if not msg_array.messages:
            logger.warning(
                f"No valid message segments for group at message: {event.raw_message}."
            )
            return

        await bot.api.post_group_msg(
            group_id=event.group_id,
            rtf=msg_array,
            reply=event.message_id,
        )


@bot.on_startup()  # pyright: ignore[reportArgumentType]
async def startup(metaevent: MetaEvent):
    logger.info("Loading chat memories...")
    if MEMORY_FILE.exists():
        try:
            with MEMORY_FILE.open("rb") as f:
                loaded = pickle.load(f)
                in_memory_memory.update(loaded)
            logger.info(f"Loaded {len(loaded)} chat memories from {MEMORY_FILE}")
        except Exception as e:
            logger.warning(f"Failed to load chat memories: {e}")

    logger.info("Logging into Pixiv...")
    await pixiv.login()
    logger.info("Pixiv login complete.")


@bot.on_shutdown()  # pyright: ignore[reportArgumentType]
async def shutdown(metaevent: MetaEvent):
    logger.info("Saving chat memories...")
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with MEMORY_FILE.open("wb") as f:
            pickle.dump(dict(in_memory_memory), f)
        logger.info(f"Saved {len(in_memory_memory)} chat memories to {MEMORY_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save chat memories: {e}")

    if pixiv.client:
        logger.info("Closing Pixiv client...")
        await pixiv.client.close()
        logger.info("Pixiv client closed.")


if __name__ == "__main__":
    bot.run()
