"""
Message Batcher - Batches messages over a time period before processing
"""

import asyncio
from typing import Any, Callable, Coroutine, Generic, List, Optional, TypeVar

TMessage = TypeVar("TMessage")
TResult = TypeVar("TResult")


class MessageBatcher(Generic[TMessage, TResult]):
    """
    Batches messages over a time period before processing them together.

    Instead of replying to each message immediately, this collects messages
    and processes them as a batch after a configurable delay.
    """

    def __init__(
        self,
        handler: Callable[[List[TMessage]], Coroutine[Any, Any, TResult]],
        batch_delay: float = 0.5,
    ):
        """
        Args:
            handler: Async function called with list of messages when batch is consumed
            batch_delay: Time in seconds to wait before auto-consuming (default 0.5s)
        """
        self.handler = handler
        self.batch_delay = batch_delay
        self._messages: List[TMessage] = []
        self._scheduled_task: Optional[asyncio.Task[None]] = None

    async def push(self, message: TMessage) -> None:
        """
        Push a message into the batcher.
        Messages are collected in order and will be consumed after batch_delay.

        Args:
            message: The message to collect
        """
        self._messages.append(message)

        # Schedule auto-consume if not already scheduled
        # No lock needed: asyncio is single-threaded, no context switch before task creation
        if self._scheduled_task is None or self._scheduled_task.done():
            self._scheduled_task = asyncio.create_task(self._schedule_consume())

    async def _schedule_consume(self) -> None:
        """Schedule consumption after the batch delay"""
        await asyncio.sleep(self.batch_delay)
        await self.consume()

    async def consume(self) -> TResult:
        """
        Consume all collected messages.

        While consuming, new messages can still be collected
        but won't be included in this batch - they'll be in the next one.

        Returns:
            The result from the handler
        """
        # Take all current messages
        messages = self._messages.copy()
        self._messages.clear()

        # Call the handler with the batch
        return await self.handler(messages)

    def pending_count(self) -> int:
        """Get the number of pending messages"""
        return len(self._messages)

    def has_pending(self) -> bool:
        """Check if there are any pending messages"""
        return self.pending_count() > 0
