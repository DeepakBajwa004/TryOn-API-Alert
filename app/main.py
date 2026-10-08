"""HTTP API: backends POST here to trigger a Telegram call and/or message."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import MAX_RING_SECONDS, MIN_RING_SECONDS, Settings
from .dispatcher import AlertDispatcher, Overloaded
from .telegram_client import TelegramAlerter

MAX_BODY_BYTES = 64 * 1024
MAX_MESSAGE_CHARS = 4000


class AlertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str | None = Field(default=None, max_length=20000)
    call: bool = True
    ring_seconds: int | None = Field(default=None, ge=MIN_RING_SECONDS, le=MAX_RING_SECONDS)

    @field_validator("message")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > MAX_MESSAGE_CHARS:
            v = v[: MAX_MESSAGE_CHARS - 15] + "\n…[truncated]"
        return v

    @model_validator(mode="after")
    def _needs_action(self) -> "AlertRequest":
        if not self.call and self.message is None:
            raise ValueError("Nothing to do: set call=true and/or provide a message")
        return self


def create_app(settings: Settings | None = None, alerter: TelegramAlerter | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    alerter = alerter or TelegramAlerter(settings)
    dispatcher = AlertDispatcher(settings, alerter)
    api_key = settings.api_key.encode()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await alerter.start()
        try:
            yield
        finally:
            await dispatcher.shutdown()
            await alerter.stop()

    app = FastAPI(
        title="Telegram Call Alert",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Payload too large"}, status_code=413)
        return await call_next(request)

    async def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        supplied = (x_api_key or "").encode()
        if not hmac.compare_digest(supplied, api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    @app.api_route("/health", methods=["GET", "HEAD"])
    async def health():
        ok = alerter.connected
        return JSONResponse({"status": "ok" if ok else "degraded"}, status_code=200 if ok else 503)

    @app.post("/v1/alert", status_code=202, dependencies=[Depends(require_api_key)])
    async def alert(body: AlertRequest):
        try:
            result = dispatcher.submit(body.message, body.call, body.ring_seconds)
        except Overloaded:
            raise HTTPException(status_code=429, detail="Too many alerts in progress", headers={"Retry-After": "30"})
        return {
            "status": "accepted",
            "alert_id": result.alert_id,
            "message_queued": result.message_queued,
            "call_queued": result.call_queued,
            "suppressed": list(result.suppressed),
        }

    return app
