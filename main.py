import asyncio
import datetime
import logging
from collections import defaultdict, deque
from functools import lru_cache
from typing import DefaultDict, Deque

from ncatbot.core import (
    BotClient,
    GroupMessageEvent,
    PrivateMessage,
)
from ncatbot.core.adapter import launch_napcat_service
from ncatbot.core.event.message_segment import MessageArray
from ncatbot.plugin_system import EventBus, PluginLoader
from ncatbot.utils import NcatBotConnectionError, ncatbot_config

from app import agents
from app.agents.group import MessageSegment
from app.collector import MessageBatchHandler
from app.configs import config
from app.database import async_session_factory
from app.memory import load_group_memories, persist_model_messages
from app.schemas import (
    Message,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    sqlalchemy_materia,
)
from app.tools import pixiv

logger = logging.getLogger("NekoLibrarian")
bot = BotClient()


# Store a batcher for each user
private_handlers: dict[int, MessageBatchHandler[PrivateMessage, None]] = {}
group_handlers: dict[
    int, MessageBatchHandler[GroupMessageEvent, list[MessageSegment]]
] = {}

in_memory_memory: DefaultDict[int, Deque[list[ModelMessage]]] = defaultdict(
    lambda: deque(maxlen=config.memory_groups_count)
)


@lru_cache(maxsize=config.batch_handler_lru_size)
def get_group_chat_batcher(
    group_id: int | str,
) -> MessageBatchHandler[GroupMessageEvent, list]:
    """Get or create a batcher for a specific group""" ""
    if group_id not in group_handlers:

        async def handle_batch(messages: list[GroupMessageEvent]):
            memories = in_memory_memory[int(group_id)]

            # if the memory is empty, try finding some from database
            if not memories:
                loaded_memories = await load_group_memories(
                    int(group_id), config.memory_groups_count
                )
                memories.extend(loaded_memories)

            last = messages.pop()
            buffered: list[ModelMessage] = [
                ModelRequest.user_text_prompt(
                    user_id=int(event.user_id),
                    user_prompt="".join(
                        f"{event.sender.card or event.sender.nickname or 'anonymous'}: {seg.text}"
                        for seg in event.message.filter_text()
                    ),
                    group_id=int(event.group_id),
                )
                for event in messages
            ]
            await persist_model_messages(buffered)
            memories.append(buffered)

            result = await agents.group.chat_agent.run(
                user_prompt=f"{last.sender.card or last.sender.nickname or 'anonymous'}: {last.raw_message}",
                message_history=[message for memory in memories for message in memory],  # pyright: ignore[reportArgumentType]
            )

            new = []
            for message in result.new_messages():
                if message.kind == "request":
                    new.append(
                        ModelRequest(
                            user_id=int(last.user_id),
                            group_id=int(group_id),
                            **message.__dict__,
                        )
                    )
                if message.kind == "response":
                    new.append(
                        ModelResponse(
                            user_id=None,
                            group_id=int(group_id),
                            **message.__dict__,
                        )
                    )
            await persist_model_messages(new)
            memories.append(new)

            return result.output

        group_handlers[int(group_id)] = MessageBatchHandler(
            handler=handle_batch,
            batch_delay=1,
        )

    return group_handlers[int(group_id)]


# @bot.on_private_message()  # pyright: ignore[reportArgumentType]
# async def handle_private_message(msg: PrivateMessage):
#     get_private_batcher(msg.user_id).push(msg)


@bot.on_group_message()  # pyright: ignore[reportArgumentType]
async def handle_group_message(event: GroupMessageEvent):
    batch_chat_handler = get_group_chat_batcher(event.group_id)
    batch_chat_handler.push(event, handle=False)

    async with async_session_factory() as session:
        session.add(
            Message(
                kind="request",
                user_id=int(event.user_id),
                group_id=int(event.group_id),
                content=event.raw_message,
                timestamp=datetime.datetime.fromtimestamp(event.time),
            )
        )
        await session.commit()

    if event.message.is_user_at(user_id=event.self_id):
        segments = await batch_chat_handler.consume()
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

        async with async_session_factory() as session:
            session.add(
                Message(
                    kind="response",
                    user_id=int(event.self_id),
                    group_id=int(event.group_id),
                    content=msg_array.concatenate_text(),
                    timestamp=datetime.datetime.fromtimestamp(event.time),
                )
            )
            await session.commit()


async def main():
    """Main entry point for running the bot."""
    with sqlalchemy_materia:
        try:
            logger.info("Logging into Pixiv...")
            await pixiv.login()
            logger.info("Pixiv login complete.")

            ncatbot_config.validate_config()

            # 加载插件

            bot.event_bus = EventBus()
            bot.plugin_loader = PluginLoader(bot.event_bus, debug=ncatbot_config.debug)

            bot._running = True

            await bot.plugin_loader.load_plugins()
            launch_napcat_service()
            await bot.adapter.connect_websocket()
        except NcatBotConnectionError:
            raise
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt caught, exiting...")
        except Exception as e:
            logger.error(f"Bot crashed with error: {e}")
            raise
        finally:
            bot.bot_exit()
            if pixiv.client:
                logger.info("Closing Pixiv client...")
                await pixiv.client.close()
                logger.info("Pixiv client closed.")


if __name__ == "__main__":
    asyncio.run(main())
