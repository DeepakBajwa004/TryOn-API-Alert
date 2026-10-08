"""Thin async wrapper around Telethon: send a message, ring a voice call."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.sessions import StringSession
from telethon.tl.functions.phone import DiscardCallRequest, RequestCallRequest
from telethon.tl.types import (
    InputPhoneCall,
    PhoneCallDiscardReasonHangup,
    PhoneCallProtocol,
)

from .config import Settings

log = logging.getLogger("alerter.telegram")

TELEGRAM_MAX_MESSAGE = 4096


class TelegramAlerter:
    def __init__(self, settings: Settings) -> None:
        self._target_name = settings.target
        self._client = TelegramClient(
            StringSession(settings.session_string),
            settings.api_id,
            settings.api_hash,
            receive_updates=False,  # we only send; skip the update firehose
        )
        # Error text contains _ * ` etc. Default markdown parsing would mangle or reject it.
        self._client.parse_mode = None
        self._peer = None
        self._call_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._client.is_connected()

    async def start(self) -> None:
        await self._client.connect()
        if not await self._client.is_user_authorized():
            await self._client.disconnect()
            raise RuntimeError("Telegram session is not authorized. Generate a fresh session string.")
        self._peer = await self._client.get_input_entity(self._target_name)
        log.info("Telegram client ready, target resolved")

    async def stop(self) -> None:
        if self._client.is_connected():
            await self._client.disconnect()

    async def send_message(self, text: str) -> None:
        if len(text) > TELEGRAM_MAX_MESSAGE:
            text = text[: TELEGRAM_MAX_MESSAGE - 15] + "\n…[truncated]"
        await self._client.send_message(self._peer, text, link_preview=False)

    async def ring(self, seconds: int) -> None:
        """Ring the target for `seconds`, then hang up. One call at a time."""
        async with self._call_lock:
            result = await self._client(
                RequestCallRequest(
                    user_id=self._peer,
                    random_id=secrets.randbits(31),
                    g_a_hash=os.urandom(32),
                    protocol=PhoneCallProtocol(
                        min_layer=92,
                        max_layer=92,
                        udp_p2p=True,
                        udp_reflector=True,
                        library_versions=["1.16.5"],
                    ),
                )
            )
            call = result.phone_call
            log.info("Call ringing (%ss)", seconds)
            try:
                await asyncio.sleep(seconds)
            finally:
                await asyncio.shield(self._hangup(call))

    async def _hangup(self, call) -> None:
        try:
            await self._client(
                DiscardCallRequest(
                    peer=InputPhoneCall(id=call.id, access_hash=call.access_hash),
                    duration=0,
                    reason=PhoneCallDiscardReasonHangup(),
                    connection_id=0,
                )
            )
        except RPCError as exc:  # already answered / declined / expired
            log.info("Hangup skipped: %s", type(exc).__name__)
        except Exception:
            log.exception("Hangup failed")
