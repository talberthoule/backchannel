"""Lightweight asyncio-based internal pub/sub for agent coordination."""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class EventBus:
    """Simple in-process event bus. Handlers run as fire-and-forget tasks."""

    def __init__(self):
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler):
        self._subscribers[event].append(handler)

    def publish(self, event: str, data: dict | None = None):
        for handler in self._subscribers.get(event, []):
            asyncio.create_task(self._safe_call(handler, data or {}))

    def clear(self):
        self._subscribers.clear()

    @staticmethod
    async def _safe_call(handler: Handler, data: dict):
        try:
            await handler(data)
        except Exception as e:
            logger.error(f"Event handler error: {e}")


class CooldownSubscriber:
    """Wraps an async handler with a minimum cooldown between invocations.

    Trailing-edge pattern: first event starts a timer. Events during the timer
    window are batched. When the timer fires, the handler runs with all
    accumulated events. An optional max_interval forces a run even if no
    events arrive (useful for the synthesizer catching implicit answers).
    """

    def __init__(
        self,
        handler: Callable[[list[dict]], Awaitable[None]],
        cooldown_seconds: float,
        max_interval_seconds: float | None = None,
    ):
        self._handler = handler
        self._cooldown = cooldown_seconds
        self._max_interval = max_interval_seconds
        self._pending: list[dict] = []
        self._timer_task: asyncio.Task | None = None
        self._max_interval_task: asyncio.Task | None = None
        self._last_run: float = 0.0
        self._stopped = False

    async def __call__(self, data: dict):
        """Called by EventBus on each event."""
        if self._stopped:
            return

        self._pending.append(data)

        # Start cooldown timer if not already running
        if self._timer_task is None or self._timer_task.done():
            self._timer_task = asyncio.create_task(self._cooldown_then_fire())

    async def start_max_interval(self):
        """Start the max-interval fallback timer. Call once during orchestrator start."""
        if self._max_interval and not self._stopped:
            self._max_interval_task = asyncio.create_task(self._max_interval_loop())

    async def _cooldown_then_fire(self):
        """Wait for cooldown, then fire handler with accumulated events."""
        await asyncio.sleep(self._cooldown)
        await self._fire()

    async def _max_interval_loop(self):
        """Fallback: ensure handler runs at least every max_interval seconds."""
        while not self._stopped:
            await asyncio.sleep(self._max_interval)
            # Nothing accumulated means nothing to reconcile. Firing anyway made
            # a silent stretch of a meeting pay for a full handler run on every
            # fallback tick (ALP-283).
            if not self._pending:
                continue
            elapsed = time.time() - self._last_run
            if elapsed >= self._max_interval - 1:  # small tolerance
                await self._fire()

    async def _fire(self):
        """Execute the handler with all pending events, then clear."""
        if self._stopped:
            return
        batch = self._pending[:]
        self._pending.clear()
        self._last_run = time.time()
        try:
            await self._handler(batch)
        except Exception as e:
            logger.error(f"CooldownSubscriber handler error: {e}")

    def stop(self):
        """Cancel pending timers."""
        self._stopped = True
        for task in [self._timer_task, self._max_interval_task]:
            if task and not task.done():
                task.cancel()
