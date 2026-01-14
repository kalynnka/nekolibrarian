"""Memory persistence and loading utilities for model messages."""

import logging
from collections.abc import Sequence

from app.database import async_session_factory
from app.schemas import ModelMessage

logger = logging.getLogger("memory")


async def persist_model_messages(messages: Sequence[ModelMessage]):
    """Persist a sequence of ModelMessage to the database asynchronously.

    Note: Must be called within a `with sqlalchemy_materia:` context.
    """
    async with async_session_factory() as session:
        session.add_all(messages)
        await session.commit()
