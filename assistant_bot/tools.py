"""Инструменты, которые Claude может вызывать: заметки, задачи, напоминания, время."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import Database, utc_now

_STR = {"type": "string"}
_INT = {"type": "integer"}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS: list[dict] = [
    _tool("get_current_time", "Текущие дата и время пользователя.", {}, []),
    _tool("add_note", "Сохранить заметку.", {"text": _STR}, ["text"]),
    _tool(
        "search_notes",
        "Показать заметки. Без query — все заметки, с query — поиск по подстроке.",
        {"query": _STR},
        [],
    ),
    _tool("delete_note", "Удалить заметку по номеру.", {"id": _INT}, ["id"]),
    _tool(
        "add_task",
        "Добавить задачу в список дел. due — необязательный срок в формате YYYY-MM-DD.",
        {"title": _STR, "due": _STR},
        ["title"],
    ),
    _tool(
        "list_tasks",
        "Показать список дел. По умолчанию только невыполненные.",
        {"include_done": {"type": "boolean"}},
        [],
    ),
    _tool("complete_task", "Отметить задачу выполненной по номеру.", {"id": _INT}, ["id"]),
    _tool(
        "set_reminder",
        "Поставить напоминание. when — местное время пользователя в формате "
        "YYYY-MM-DD HH:MM, обязательно в будущем. Бот сам напишет пользователю в это время.",
        {"text": _STR, "when": _STR},
        ["text", "when"],
    ),
    _tool("list_reminders", "Показать активные напоминания.", {}, []),
    _tool("cancel_reminder", "Отменить напоминание по номеру.", {"id": _INT}, ["id"]),
]


class ToolExecutor:
    """Выполняет вызовы инструментов от имени одного пользователя."""

    def __init__(self, db: Database, tz: ZoneInfo, user_id: int, chat_id: int):
        self.db, self.tz, self.user_id, self.chat_id = db, tz, user_id, chat_id

    def now_local(self) -> datetime:
        return datetime.now(self.tz).replace(microsecond=0)

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Возвращает (результат, is_error)."""
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            return f"Неизвестный инструмент: {name}", True
        try:
            return handler(**args), False
        except (ValueError, TypeError) as exc:
            return f"Ошибка: {exc}", True

    # --- инструменты -------------------------------------------------------
    def _t_get_current_time(self) -> str:
        return self.now_local().strftime("%Y-%m-%d %H:%M (%A), ") + str(self.tz)

    def _t_add_note(self, text: str) -> str:
        return f"Заметка #{self.db.add_note(self.user_id, text)} сохранена."

    def _t_search_notes(self, query: str | None = None) -> str:
        rows = self.db.search_notes(self.user_id, query)
        if not rows:
            return "Заметок нет."
        return "\n".join(f"#{r['id']}: {r['text']}" for r in rows)

    def _t_delete_note(self, id: int) -> str:
        ok = self.db.delete_note(self.user_id, id)
        return f"Заметка #{id} удалена." if ok else f"Заметка #{id} не найдена."

    def _t_add_task(self, title: str, due: str | None = None) -> str:
        if due:
            datetime.strptime(due, "%Y-%m-%d")  # ValueError при неверном формате
        return f"Задача #{self.db.add_task(self.user_id, title, due)} добавлена."

    def _t_list_tasks(self, include_done: bool = False) -> str:
        rows = self.db.list_tasks(self.user_id, include_done)
        if not rows:
            return "Задач нет."
        return "\n".join(
            f"#{r['id']} [{'x' if r['done'] else ' '}] {r['title']}"
            + (f" (срок {r['due']})" if r["due"] else "")
            for r in rows
        )

    def _t_complete_task(self, id: int) -> str:
        ok = self.db.complete_task(self.user_id, id)
        return f"Задача #{id} выполнена." if ok else f"Задача #{id} не найдена."

    def _t_set_reminder(self, text: str, when: str) -> str:
        local = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=self.tz)
        if local <= self.now_local():
            raise ValueError("время напоминания уже прошло")
        due_utc = local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        rid = self.db.add_reminder(self.user_id, self.chat_id, text, due_utc)
        return f"Напоминание #{rid} поставлено на {when} ({self.tz})."

    def _t_list_reminders(self) -> str:
        rows = self.db.list_reminders(self.user_id)
        if not rows:
            return "Активных напоминаний нет."
        out = []
        for r in rows:
            due = datetime.strptime(r["due_at"], "%Y-%m-%dT%H:%M:%S")
            local = due.replace(tzinfo=ZoneInfo("UTC")).astimezone(self.tz)
            out.append(f"#{r['id']} {local:%Y-%m-%d %H:%M}: {r['text']}")
        return "\n".join(out)

    def _t_cancel_reminder(self, id: int) -> str:
        ok = self.db.cancel_reminder(self.user_id, id)
        return f"Напоминание #{id} отменено." if ok else f"Напоминание #{id} не найдено."


def format_tool_input(args: dict) -> str:
    return json.dumps(args, ensure_ascii=False)
