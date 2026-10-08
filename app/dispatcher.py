"""Alert orchestration: dedup, call cooldown, in-flight cap, background execution."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass

from telethon.errors import FloodWaitError, RPCError

from .config import Settings
from .telegram_client import TelegramAlerter

log = logging.getLogger("alerter.dispatch")


class Overloaded(Exception):
    """Too many alerts already in flight."""


@dataclass(frozen=True, slots=True)
class Accepted:
    alert_id: str
    message_queued: bool
    call_queued: bool
    suppressed: tuple[str, ...]


class AlertDispatcher:
    def __init__(self, settings: Settings, alerter: TelegramAlerter) -> None:
        self._s = settings
        self._alerter = alerter
        self._tasks: set[asyncio.Task] = set()
        self._seen: dict[str, float] = {}  # message hash -> expiry (monotonic)
        self._call_blocked_until = 0.0

    def submit(self, text: str | None, call: bool, ring_seconds: int | None) -> Accepted:
        if len(self._tasks) >= self._s.max_inflight:
            raise Overloaded
        now = time.monotonic()
        suppressed: list[str] = []

        send_text = text
        if send_text is not None and self._is_duplicate(send_text, now):
            send_text = None
            suppressed.append("duplicate_message")

        do_call = call
        if do_call and now < self._call_blocked_until:
            do_call = False
            suppressed.append("call_cooldown")

        alert_id = uuid.uuid4().hex[:12]
        ring = ring_seconds or self._s.default_ring_seconds
        if do_call:
            # Reserve cooldown immediately so concurrent hits cannot all ring.
            self._call_blocked_until = now + ring + self._s.call_cooldown_seconds

        if send_text is not None or do_call:
            task = asyncio.create_task(self._run(alert_id, send_text, do_call, ring))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        return Accepted(alert_id, send_text is not None, do_call, tuple(suppressed))

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _is_duplicate(self, text: str, now: float) -> bool:
        window = self._s.dedup_window_seconds
        if window <= 0:
            return False
        self._seen = {k: exp for k, exp in self._seen.items() if exp > now}
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in self._seen:
            return True
        self._seen[key] = now + window
        return False

    async def _run(self, alert_id: str, text: str | None, call: bool, ring: int) -> None:
        # Message and call are independent: one failing never blocks the other.
        if text is not None:
            try:
                await self._alerter.send_message(text)
                log.info("[%s] message sent", alert_id)
            except FloodWaitError as exc:
                log.error("[%s] message hit FloodWait %ss", alert_id, exc.seconds)
            except Exception:
                log.exception("[%s] message failed", alert_id)

        if call:
            try:
                await self._alerter.ring(ring)
                log.info("[%s] call finished", alert_id)
            except asyncio.CancelledError:
                raise
            except FloodWaitError as exc:
                self._call_blocked_until = time.monotonic() + exc.seconds
                log.error("[%s] call hit FloodWait %ss", alert_id, exc.seconds)
            except RPCError as exc:
                self._call_blocked_until = 0.0  # allow retry
                log.error("[%s] call rejected: %s", alert_id, type(exc).__name__)
            except Exception:
                self._call_blocked_until = 0.0
                log.exception("[%s] call failed", alert_id)
