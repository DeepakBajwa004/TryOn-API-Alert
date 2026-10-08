"""Environment-driven configuration. Fails fast on startup if anything is wrong."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

MAX_RING_SECONDS = 120
MIN_RING_SECONDS = 5
MIN_API_KEY_LENGTH = 32

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class Settings:
    api_id: int
    api_hash: str
    session_string: str
    target: str
    api_key: str
    default_ring_seconds: int
    call_cooldown_seconds: int
    dedup_window_seconds: int
    max_inflight: int
    log_level: str

    def __repr__(self) -> str:  # never leak secrets into logs
        return f"Settings(target={self.target!r}, default_ring_seconds={self.default_ring_seconds})"

    @classmethod
    def from_env(cls) -> "Settings":
        api_id_raw = _required("TG_API_ID")
        if not api_id_raw.isdigit():
            raise ConfigError("TG_API_ID must be numeric")

        target = _required("TG_TARGET").lstrip("@")
        if not _USERNAME_RE.match(target):
            raise ConfigError(
                "TG_TARGET must be a Telegram @username (5-32 chars: letters, digits, underscore). "
                "Numeric IDs are not supported because a fresh session cannot resolve them."
            )

        api_key = _required("ALERT_API_KEY")
        if len(api_key) < MIN_API_KEY_LENGTH:
            raise ConfigError(f"ALERT_API_KEY must be at least {MIN_API_KEY_LENGTH} characters")

        return cls(
            api_id=int(api_id_raw),
            api_hash=_required("TG_API_HASH"),
            session_string=_required("TG_SESSION_STRING"),
            target=target,
            api_key=api_key,
            default_ring_seconds=_int(
                "DEFAULT_RING_SECONDS", 30, minimum=MIN_RING_SECONDS, maximum=MAX_RING_SECONDS
            ),
            call_cooldown_seconds=_int("CALL_COOLDOWN_SECONDS", 60, minimum=0, maximum=3600),
            dedup_window_seconds=_int("DEDUP_WINDOW_SECONDS", 30, minimum=0, maximum=3600),
            max_inflight=_int("MAX_INFLIGHT", 20, minimum=1, maximum=200),
            log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
