import asyncio
import logging
import signal
from collections import defaultdict, deque
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import DefaultDict, Deque

from ncatbot.core import BotClient, GroupMessageEvent, MetaEvent, PrivateMessage
from ncatbot.core.event.message_segment import MessageArray
from sqlalchemy import distinct, func, select

from app import agents
from app.collector import MessageBatchHandler
from app.configs import config
from app.database import async_session_factory
from app.models import ModelMessage as ModelMessageORM
from app.schemas import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    sqlalchemy_materia,
)
from app.tools import pixiv

logger = logging.getLogger("NekoLibrarian")
bot = BotClient()


# Store a batcher for each user
private_handlers: dict[int, MessageBatchHandler[PrivateMessage, None]] = {}
group_handlers: dict[int, MessageBatchHandler[GroupMessageEvent, list]] = {}

# TODO: persist chat memory to PG
MEMORY_FILE = Path("./data/chat_memory.pkl")
in_memory_memory: DefaultDict[int, Deque[list[ModelMessage]]] = defaultdict(
    lambda: deque(maxlen=config.memory_groups_count)
)


# @lru_cache(maxsize=config.batch_handler_lru_size)
# def get_private_batcher(
#     user_id: int | str,
# ) -> MessageBatchHandler[PrivateMessage, None]:
#     """Get or create a batcher for a specific user"""
#     if user_id not in private_handlers:

#         async def handle_batch(messages: List[PrivateMessage]) -> None:
#             await bot.api.set_input_status(user_id=user_id, event_type=1)
#             memories = in_memory_memory[int(user_id)]
#             result = await agents.private.chat_agent.run(
#                 user_prompt="\n".join([msg.raw_message for msg in messages]),
#                 message_history=[message for memory in memories for message in memory],
#             )
#             memories.append(result.new_messages())
#             for msg in result.output:
#                 if msg.strip():
#                     await bot.api.post_private_msg(
#                         user_id=user_id,
#                         text=msg,
#                     )

#         private_handlers[int(user_id)] = MessageBatchHandler(
#             handler=handle_batch,
#             batch_delay=0.5,
#         )

#     return private_handlers[int(user_id)]


async def persist_messages(messages: Sequence[ModelMessage]):
    """Persist a sequence of ModelMessage to the database asynchronously.

    Note: Must be called within a `with sqlalchemy_materia:` context.
    """
    async with async_session_factory() as session:
        session.add_all(messages)
        await session.commit()


async def load_group_memories(group_id: int, limit: int) -> list[list[ModelMessage]]:
    """Load latest N turns of memories for a specific group from database.

    Returns a list of turns, where each turn is a list of ModelMessage.
    Messages are grouped by run_id, and orphan messages between run_ids form their own turns.
    """

    async with async_session_factory() as session:
        # Get the latest N distinct run_ids ordered by their max timestamp
        latest_run_ids_stmt = (
            select(ModelMessageORM.run_id)
            .where(
                ModelMessageORM.group_id == group_id,
                ModelMessageORM.run_id.isnot(None),
            )
            .group_by(ModelMessageORM.run_id)
            .order_by(func.max(ModelMessageORM.timestamp).desc())
            .limit(limit)
        )
        result = await session.execute(latest_run_ids_stmt)
        run_ids = [row[0] for row in result.all()]

        if not run_ids:
            return []

        # Fetch all messages with those run_ids, plus orphan messages in the same time range
        # First, get the time range
        time_range_stmt = select(
            func.min(ModelMessageORM.timestamp).label("start"),
            func.max(ModelMessageORM.timestamp).label("end"),
        ).where(
            ModelMessageORM.group_id == group_id,
            ModelMessageORM.run_id.in_(run_ids),
        )
        time_result = await session.execute(time_range_stmt)
        time_range = time_result.one()

        if not time_range.start or not time_range.end:
            return []

        # Fetch all messages in that time range
        stmt = (
            select(ModelMessageORM)
            .where(
                ModelMessageORM.group_id == group_id,
                ModelMessageORM.timestamp >= time_range.start,
                ModelMessageORM.timestamp <= time_range.end,
            )
            .order_by(ModelMessageORM.timestamp.asc(), ModelMessageORM.id.asc())
        )

        result = await session.execute(stmt)
        messages = list(result.scalars().all())

        if not messages:
            return []

        # Group messages by run_id first
        turns_orm = []
        current_turn = []
        current_run_id = messages[0].run_id

        for msg in messages:
            # Start a new turn when run_id changes
            if msg.run_id != current_run_id:
                if current_turn:
                    turns_orm.append(current_turn)
                current_turn = [msg]
                current_run_id = msg.run_id
            else:
                current_turn.append(msg)

        # Add the last turn
        if current_turn:
            turns_orm.append(current_turn)

        return [ModelMessagesTypeAdapter.validate_python(turn) for turn in turns_orm]


async def load_all_group_memories() -> dict[int, list[list[ModelMessage]]]:
    """Load memories for all groups from database in parallel.

    Returns a dict mapping group_id to list of turns.
    """
    with sqlalchemy_materia:
        async with async_session_factory() as session:
            # Get all distinct group_ids
            stmt = select(distinct(ModelMessageORM.group_id)).where(
                ModelMessageORM.group_id.isnot(None)
            )
            result = await session.execute(stmt)
            group_ids = [row[0] for row in result.all()]

        logger.info(f"Found {len(group_ids)} groups with message history")

        # Load memories for all groups in parallel using TaskGroup
        memories = {}
        async with asyncio.TaskGroup() as tg:
            tasks = {
                group_id: tg.create_task(
                    load_group_memories(group_id, config.memory_groups_count)
                )
                for group_id in group_ids
            }

        # Collect results
        for group_id, task in tasks.items():
            turns = task.result()
            if turns:
                memories[group_id] = turns
                logger.info(f"Loaded {len(turns)} turns for group {group_id}")

        return memories


@lru_cache(maxsize=config.batch_handler_lru_size)
def get_group_batcher(
    group_id: int | str,
) -> MessageBatchHandler[GroupMessageEvent, list]:
    """Get or create a batcher for a specific group""" ""
    if group_id not in group_handlers:

        async def handle_batch(messages: list[GroupMessageEvent]):
            with sqlalchemy_materia:
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
                await persist_messages(buffered)
                memories.append(buffered)

                result = await agents.group.chat_agent.run(
                    user_prompt=f"{last.sender.card or last.sender.nickname or 'anonymous'}: {last.raw_message}",
                    message_history=[
                        message for memory in memories for message in memory
                    ],  # pyright: ignore[reportArgumentType]
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
                await persist_messages(new)
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
    logger.info("Logging into Pixiv...")
    await pixiv.login()
    logger.info("Pixiv login complete.")


@bot.on_shutdown()  # pyright: ignore[reportArgumentType]
async def shutdown(metaevent: MetaEvent):
    await save_memories_and_cleanup()


async def save_memories_and_cleanup():
    """Shared cleanup logic for shutdown"""
    if pixiv.client:
        logger.info("Closing Pixiv client...")
        await pixiv.client.close()
        logger.info("Pixiv client closed.")


if __name__ == "__main__":
    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        # Run cleanup directly since bot framework doesn't properly handle signals
        try:
            asyncio.run(save_memories_and_cleanup())
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught, exiting...")
    except Exception as e:
        logger.error(f"Bot crashed with error: {e}")
        raise
