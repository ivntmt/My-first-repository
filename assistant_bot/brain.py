"""Диалог с Claude: системный промпт, цикл вызова инструментов, история."""

from __future__ import annotations

import logging

import anthropic

from .config import Config
from .db import Database
from .tools import TOOLS, ToolExecutor, format_tool_input

log = logging.getLogger(__name__)

MAX_TOOL_STEPS = 8
MAX_TOKENS = 16000

SYSTEM_PROMPT = """\
Ты — личный ассистент пользователя в Telegram. Помогаешь с повседневными делами: \
отвечаешь на вопросы, ведёшь заметки и список дел, ставишь напоминания, помогаешь \
формулировать и планировать.

Правила:
- Отвечай на том языке, на котором пишет пользователь. Коротко и по делу: это чат в мессенджере.
- Пиши обычным текстом, без Markdown-разметки (заголовков, таблиц, ``` и т. п.).
- Заметки, задачи и напоминания сохраняй только через инструменты. Не говори, что что-то \
сохранено или поставлено, пока инструмент не вернул успех.
- Для напоминаний переводи относительное время («завтра в 9», «через час») в точную дату и \
время по часам пользователя, опираясь на текущее время ниже. Если время неясно — уточни.
- Не выдумывай факты. Если не знаешь или у тебя нет нужного инструмента, скажи об этом прямо.

Сейчас у пользователя: {now}
"""


class Assistant:
    def __init__(self, cfg: Config, db: Database, client: anthropic.AsyncAnthropic | None = None):
        self.cfg = cfg
        self.db = db
        self.client = client or anthropic.AsyncAnthropic()

    async def reply(self, user_id: int, chat_id: int, text: str) -> str:
        executor = ToolExecutor(self.db, self.cfg.timezone, user_id, chat_id)
        system = SYSTEM_PROMPT.format(now=executor._t_get_current_time())
        messages = self.db.get_history(chat_id, self.cfg.history_messages)
        messages.append({"role": "user", "content": text})

        answer = ""
        for _ in range(MAX_TOOL_STEPS):
            response = await self.client.messages.create(
                model=self.cfg.model,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": self.cfg.effort},
            )

            if response.stop_reason == "refusal":
                answer = "Не могу помочь с этим запросом."
                break

            if response.stop_reason == "tool_use":
                # Блоки ответа (включая thinking) возвращаем в историю без изменений.
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    output, is_error = executor.run(block.name, block.input)
                    log.info("tool %s(%s) -> %s", block.name, format_tool_input(block.input), output)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                            "is_error": is_error,
                        }
                    )
                # Все результаты параллельных вызовов — в одном сообщении.
                messages.append({"role": "user", "content": results})
                continue

            answer = "".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "max_tokens":
                answer += "\n\n(ответ оборван из-за ограничения длины)"
            break
        else:
            answer = "Не удалось закончить: слишком много шагов подряд. Попробуйте переформулировать."

        answer = answer or "(пустой ответ)"
        self.db.add_history(chat_id, "user", text)
        self.db.add_history(chat_id, "assistant", answer)
        return answer
