# Личный ассистент в Telegram

Telegram-бот на базе Claude. Общается обычным языком и умеет:

- вести **заметки** (записать, найти, удалить);
- вести **список дел** со сроками;
- ставить **напоминания** — бот сам напишет в нужное время (переживают перезапуск);
- отвечать на вопросы и помогать формулировать и планировать.

Доступ только для пользователей из `ALLOWED_USER_IDS`. Данные хранятся локально в SQLite.

## Запуск

1. Создай бота у [@BotFather](https://t.me/BotFather) и получи токен.
2. Получи ключ API на https://console.anthropic.com.
3. Установи и настрой:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # впиши токен, ключ и часовой пояс
   ```

4. Запусти `python -m assistant_bot`, напиши боту `/start` — он покажет твой Telegram ID.
   Впиши его в `ALLOWED_USER_IDS` в `.env` и перезапусти бота.

Бот работает через long polling, публичный адрес не нужен. Для постоянной работы запусти его
на сервере (systemd, Docker, `tmux` — что удобнее).

## Устройство

| Файл | Назначение |
|---|---|
| `assistant_bot/bot.py` | Telegram: команды, whitelist, отправка напоминаний |
| `assistant_bot/brain.py` | Диалог с Claude и цикл вызова инструментов |
| `assistant_bot/tools.py` | Инструменты: заметки, задачи, напоминания, время |
| `assistant_bot/db.py` | SQLite-хранилище |
| `assistant_bot/config.py` | Настройки из `.env` |

Новая возможность = новая функция `_t_<имя>` в `ToolExecutor` + описание в `TOOLS`.

## Тесты

```bash
pip install pytest
pytest
```

Тесты не обращаются к сети: ответы Claude подменяются заглушкой.
