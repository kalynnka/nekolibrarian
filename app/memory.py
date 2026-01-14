"""Memory persistence and loading utilities for model messages."""

import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy import distinct, func, select

from app.configs import config
from app.database import async_session_factory
from app.models import ModelMessage as ModelMessageORM
from app.schemas import ModelMessage, ModelMessagesTypeAdapter, sqlalchemy_materia

logger = logging.getLogger("memory")


async def persist_model_messages(messages: Sequence[ModelMessage]):
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
