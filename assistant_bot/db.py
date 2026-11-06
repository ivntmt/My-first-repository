"""SQLite-хранилище: заметки, задачи, напоминания и история диалога.

Все запросы привязаны к user_id, поэтому данные разных пользователей не смешиваются.
Время хранится в UTC в формате ISO без часового пояса ("2026-11-06T18:30:00").
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)


def to_ts(dt: datetime) -> str:
    return dt.strftime(TS_FORMAT)


SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    due TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    # --- заметки -----------------------------------------------------------
    def add_note(self, user_id: int, text: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO notes (user_id, text, created_at) VALUES (?, ?, ?)",
            (user_id, text, to_ts(utc_now())),
        )
        self._conn.commit()
        return cur.lastrowid

    def search_notes(self, user_id: int, query: str | None = None) -> list[sqlite3.Row]:
        rows = self._conn.execute(
            "SELECT * FROM notes WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        if query:
            # lower()/LIKE в SQLite понимают регистр только у ASCII, поэтому ищем в Python.
            needle = query.casefold()
            rows = [r for r in rows if needle in r["text"].casefold()]
        return rows

    def delete_note(self, user_id: int, note_id: int) -> bool:
        cur = self._conn.execute(
            "DELETE FROM notes WHERE user_id = ? AND id = ?", (user_id, note_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # --- задачи ------------------------------------------------------------
    def add_task(self, user_id: int, title: str, due: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO tasks (user_id, title, due, created_at) VALUES (?, ?, ?, ?)",
            (user_id, title, due, to_ts(utc_now())),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_tasks(self, user_id: int, include_done: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM tasks WHERE user_id = ?"
        if not include_done:
            sql += " AND done = 0"
        sql += " ORDER BY due IS NULL, due, id"
        return self._conn.execute(sql, (user_id,)).fetchall()

    def complete_task(self, user_id: int, task_id: int) -> bool:
        cur = self._conn.execute(
            "UPDATE tasks SET done = 1 WHERE user_id = ? AND id = ?", (user_id, task_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # --- напоминания -------------------------------------------------------
    def add_reminder(self, user_id: int, chat_id: int, text: str, due_at: datetime) -> int:
        cur = self._conn.execute(
            "INSERT INTO reminders (user_id, chat_id, text, due_at) VALUES (?, ?, ?, ?)",
            (user_id, chat_id, text, to_ts(due_at)),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_reminders(self, user_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND sent = 0 ORDER BY due_at",
            (user_id,),
        ).fetchall()

    def cancel_reminder(self, user_id: int, reminder_id: int) -> bool:
        cur = self._conn.execute(
            "DELETE FROM reminders WHERE user_id = ? AND id = ? AND sent = 0",
            (user_id, reminder_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def due_reminders(self, now: datetime) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM reminders WHERE sent = 0 AND due_at <= ? ORDER BY due_at",
            (to_ts(now),),
        ).fetchall()

    def mark_reminder_sent(self, reminder_id: int) -> None:
        self._conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        self._conn.commit()

    # --- история диалога ---------------------------------------------------
    def add_history(self, chat_id: int, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO history (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )
        self._conn.commit()

    def get_history(self, chat_id: int, limit: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT role, content FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)  # диалог для API должен начинаться с реплики пользователя
        return messages

    def clear_history(self, chat_id: int) -> None:
        self._conn.execute("DELETE FROM history WHERE chat_id = ?", (chat_id,))
        self._conn.commit()
