"""Telegram-часть: хендлеры сообщений, доступ по whitelist, отправка напоминаний."""

from __future__ import annotations

import asyncio
import logging

import anthropic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .brain import Assistant
from .config import Config
from .db import Database, utc_now

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
REMINDER_POLL_SECONDS = 20

HELP = (
    "Я твой личный ассистент. Просто пиши как человеку:\n"
    "• «запиши: пароль от wifi — 12345»\n"
    "• «добавь задачу купить молоко до 2026-11-10»\n"
    "• «напомни завтра в 9:00 позвонить маме»\n"
    "• «что у меня в списке дел?»\n\n"
    "Команды: /reset — забыть переписку (заметки и задачи остаются), /help — это сообщение."
)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


class AssistantBot:
    def __init__(self, cfg: Config, db: Database, assistant: Assistant):
        self.cfg, self.db, self.assistant = cfg, db, assistant
        self._locks: dict[int, asyncio.Lock] = {}

    def build(self) -> Application:
        app = Application.builder().token(self.cfg.telegram_token).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("reset", self.cmd_reset))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.job_queue.run_repeating(self.send_due_reminders, REMINDER_POLL_SECONDS, first=5)
        return app

    def _allowed(self, update: Update) -> bool:
        user = update.effective_user
        return user is not None and user.id in self.cfg.allowed_user_ids

    async def _deny(self, update: Update) -> None:
        user = update.effective_user
        uid = user.id if user else "?"
        log.warning("отказ в доступе user_id=%s", uid)
        await update.effective_message.reply_text(
            f"Доступ закрыт. Твой Telegram ID: {uid}. Владелец бота может добавить его "
            "в ALLOWED_USER_IDS."
        )

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        await update.effective_message.reply_text("Привет! " + HELP)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        await update.effective_message.reply_text(HELP)

    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        self.db.clear_history(update.effective_chat.id)
        await update.effective_message.reply_text("Переписку забыл. Заметки, задачи и напоминания на месте.")

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        async with lock:  # сообщения одного чата обрабатываем по очереди
            await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
            try:
                answer = await self.assistant.reply(user_id, chat_id, update.effective_message.text)
            except anthropic.APIError:
                log.exception("ошибка Claude API")
                answer = "Не получилось связаться с Claude. Попробуй ещё раз чуть позже."
        for part in split_message(answer):
            await update.effective_message.reply_text(part)

    async def send_due_reminders(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        for r in self.db.due_reminders(utc_now()):
            try:
                await context.bot.send_message(r["chat_id"], f"⏰ Напоминание: {r['text']}")
            except Exception:
                log.exception("не удалось отправить напоминание #%s", r["id"])
                continue  # повторим на следующем проходе
            self.db.mark_reminder_sent(r["id"])
