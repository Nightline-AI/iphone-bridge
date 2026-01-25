"""
Message Queue - Retry failed webhook deliveries.

Stores messages that failed to deliver to Nightline and retries them
with exponential backoff.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Max messages to hold in queue (prevent memory blowup)
MAX_QUEUE_SIZE = 1000

# Retry settings
MAX_RETRIES = 10
BASE_DELAY = 5  # seconds
MAX_DELAY = 300  # 5 minutes max


@dataclass
class QueuedMessage:
    """A message waiting to be delivered."""
    id: str
    payload: dict
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    next_retry_at: float = 0

    def calculate_next_retry(self):
        """Exponential backoff with jitter."""
        delay = min(BASE_DELAY * (2 ** self.attempts), MAX_DELAY)
        # Add some jitter (±20%)
        import random
        jitter = delay * 0.2 * (random.random() - 0.5)
        self.next_retry_at = time.time() + delay + jitter
        self.attempts += 1


class MessageQueue:
    """
    In-memory queue for failed message deliveries.
    
    Usage:
        queue = MessageQueue(deliver_fn=nightline_client.forward_message)
        await queue.start()
        
        # When a message fails to deliver:
        queue.enqueue(message_id, payload)
    """

    def __init__(
        self,
        deliver_fn: Callable[[dict], Awaitable[bool]],
        max_size: int = MAX_QUEUE_SIZE,
    ):
        self.deliver_fn = deliver_fn
        self.max_size = max_size
        self._queue: dict[str, QueuedMessage] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def size(self) -> int:
        return len(self._queue)

    @property
    def is_running(self) -> bool:
        return self._running

    def enqueue(self, message_id: str, payload: dict) -> bool:
        """
        Add a message to the retry queue.
        
        Returns False if queue is full.
        """
        if message_id in self._queue:
            logger.debug(f"Message {message_id} already in queue")
            return True

        if len(self._queue) >= self.max_size:
            logger.error(f"Queue full ({self.max_size}), dropping message {message_id}")
            return False

        msg = QueuedMessage(id=message_id, payload=payload)
        msg.calculate_next_retry()
        self._queue[message_id] = msg
        logger.info(f"Queued message {message_id} for retry (queue size: {len(self._queue)})")
        return True

    def remove(self, message_id: str):
        """Remove a message from the queue (after successful delivery)."""
        self._queue.pop(message_id, None)

    async def _process_queue(self):
        """Process queued messages."""
        while self._running:
            now = time.time()
            to_retry = [
                msg for msg in self._queue.values()
                if msg.next_retry_at <= now
            ]

            for msg in to_retry:
                if msg.attempts >= MAX_RETRIES:
                    logger.error(f"Message {msg.id} exceeded max retries, dropping")
                    self._queue.pop(msg.id, None)
                    continue

                logger.info(f"Retrying message {msg.id} (attempt {msg.attempts + 1})")
                
                try:
                    success = await self.deliver_fn(msg.payload)
                    if success:
                        logger.info(f"Message {msg.id} delivered successfully")
                        self._queue.pop(msg.id, None)
                    else:
                        msg.calculate_next_retry()
                        logger.warning(
                            f"Message {msg.id} delivery failed, "
                            f"retry in {msg.next_retry_at - time.time():.0f}s"
                        )
                except Exception as e:
                    msg.calculate_next_retry()
                    logger.error(f"Error delivering message {msg.id}: {e}")

            await asyncio.sleep(1)

    async def start(self):
        """Start the queue processor."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_queue())
        logger.info("Message queue started")

    def stop(self):
        """Stop the queue processor."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info(f"Message queue stopped ({len(self._queue)} messages pending)")

    def get_stats(self) -> dict:
        """Get queue statistics for health endpoint."""
        now = time.time()
        oldest = min((m.created_at for m in self._queue.values()), default=now)
        
        return {
            "size": len(self._queue),
            "max_size": self.max_size,
            "oldest_message_age_seconds": now - oldest if self._queue else 0,
            "messages_by_attempts": {
                i: sum(1 for m in self._queue.values() if m.attempts == i)
                for i in range(MAX_RETRIES + 1)
                if any(m.attempts == i for m in self._queue.values())
            },
        }
