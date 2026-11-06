"""Настройки бота из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


def _parse_ids(raw: str) -> frozenset[int]:
    return frozenset(int(p) for p in raw.replace(";", ",").split(",") if p.strip())


@dataclass(frozen=True)
class Config:
    telegram_token: str
    allowed_user_ids: frozenset[int]
    timezone: ZoneInfo
    model: str
    effort: str
    db_path: str
    history_messages: int

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit("Не задан TELEGRAM_BOT_TOKEN (см. .env.example)")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Не задан ANTHROPIC_API_KEY (см. .env.example)")
        return cls(
            telegram_token=token,
            allowed_user_ids=_parse_ids(os.environ.get("ALLOWED_USER_IDS", "")),
            timezone=ZoneInfo(os.environ.get("TIMEZONE", "UTC")),
            model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
            effort=os.environ.get("CLAUDE_EFFORT", "medium"),
            db_path=os.environ.get("DB_PATH", "data/assistant.db"),
            history_messages=int(os.environ.get("HISTORY_MESSAGES", "30")),
        )
