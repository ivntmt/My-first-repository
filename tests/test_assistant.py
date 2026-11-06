import asyncio
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from assistant_bot.bot import split_message
from assistant_bot.brain import Assistant
from assistant_bot.config import Config
from assistant_bot.db import Database, utc_now
from assistant_bot.tools import ToolExecutor

TZ = ZoneInfo("Europe/Moscow")


@pytest.fixture
def db():
    return Database(":memory:")


@pytest.fixture
def ex(db):
    return ToolExecutor(db, TZ, user_id=1, chat_id=10)


def make_cfg():
    return Config(
        telegram_token="t",
        allowed_user_ids=frozenset({1}),
        timezone=TZ,
        model="claude-opus-5-5",
        effort="medium",
        db_path=":memory:",
        history_messages=30,
    )


# --- инструменты -------------------------------------------------------------
def test_notes_are_per_user(db):
    a = ToolExecutor(db, TZ, 1, 10)
    b = ToolExecutor(db, TZ, 2, 20)
    a.run("add_note", {"text": "купить хлеб"})
    assert "хлеб" in a.run("search_notes", {})[0]
    assert b.run("search_notes", {})[0] == "Заметок нет."
    assert "не найдена" in b.run("delete_note", {"id": 1})[0]
    assert "удалена" in a.run("delete_note", {"id": 1})[0]


def test_note_search(ex):
    ex.run("add_note", {"text": "Пароль от wifi"})
    ex.run("add_note", {"text": "позвонить маме"})
    out, err = ex.run("search_notes", {"query": "ПАРОЛЬ"})
    assert not err and "wifi" in out and "маме" not in out


def test_tasks_flow(ex):
    ex.run("add_task", {"title": "A", "due": "2026-12-01"})
    ex.run("add_task", {"title": "B"})
    assert ex.run("list_tasks", {})[0].count("#") == 2
    ex.run("complete_task", {"id": 1})
    assert "A" not in ex.run("list_tasks", {})[0]
    assert "[x] A" in ex.run("list_tasks", {"include_done": True})[0]


def test_task_bad_date(ex):
    out, err = ex.run("add_task", {"title": "x", "due": "завтра"})
    assert err


def test_reminder_roundtrip_and_due(db, ex):
    when = (ex.now_local() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    out, err = ex.run("set_reminder", {"text": "позвонить", "when": when})
    assert not err, out
    assert when in ex.run("list_reminders", {})[0]
    assert db.due_reminders(utc_now()) == []
    assert len(db.due_reminders(utc_now() + timedelta(hours=2))) == 1
    db.mark_reminder_sent(1)
    assert db.due_reminders(utc_now() + timedelta(hours=2)) == []


def test_reminder_in_past_rejected(ex):
    out, err = ex.run("set_reminder", {"text": "x", "when": "2000-01-01 10:00"})
    assert err and "прошло" in out


def test_reminder_bad_format_and_unknown_tool(ex):
    assert ex.run("set_reminder", {"text": "x", "when": "завтра"})[1]
    assert ex.run("nope", {})[1]
    assert ex.run("add_note", {})[1]  # нет обязательного аргумента -> TypeError


def test_history_starts_with_user(db):
    db.add_history(5, "assistant", "orphan")
    db.add_history(5, "user", "hi")
    db.add_history(5, "assistant", "hello")
    assert [m["role"] for m in db.get_history(5, 30)] == ["user", "assistant"]
    db.clear_history(5)
    assert db.get_history(5, 30) == []


def test_split_message():
    assert split_message("abc") == ["abc"]
    parts = split_message("x" * 5000)
    assert all(len(p) <= 4096 for p in parts) and "".join(parts) == "x" * 5000


# --- цикл Claude с поддельным клиентом ---------------------------------------
class FakeClient:
    """Первый ответ — вызов add_note, второй — финальный текст."""

    def __init__(self):
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            block = SimpleNamespace(type="tool_use", id="tu_1", name="add_note", input={"text": "молоко"})
            return SimpleNamespace(stop_reason="tool_use", content=[block])
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Готово")])


def test_agent_loop_runs_tool_and_saves_history(db):
    client = FakeClient()
    bot = Assistant(make_cfg(), db, client)
    answer = asyncio.run(bot.reply(1, 10, "запиши молоко"))
    assert answer == "Готово"
    assert db.search_notes(1)[0]["text"] == "молоко"

    second = client.calls[1]["messages"]
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "tu_1"
    assert client.calls[0]["output_config"] == {"effort": "medium"}
    assert [m["role"] for m in db.get_history(10, 30)] == ["user", "assistant"]


def test_refusal_is_handled(db):
    async def create(**kw):
        return SimpleNamespace(stop_reason="refusal", content=[])

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    answer = asyncio.run(Assistant(make_cfg(), db, client).reply(1, 10, "x"))
    assert "Не могу" in answer
