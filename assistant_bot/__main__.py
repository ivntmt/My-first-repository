"""Запуск: python -m assistant_bot"""

import logging

from dotenv import load_dotenv

from .bot import AssistantBot
from .brain import Assistant
from .config import Config
from .db import Database


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = Config.from_env()
    if not cfg.allowed_user_ids:
        logging.warning(
            "ALLOWED_USER_IDS пуст: бот никого не пустит. Напиши ему /start, он покажет твой ID."
        )
    db = Database(cfg.db_path)
    bot = AssistantBot(cfg, db, Assistant(cfg, db))
    bot.build().run_polling()


if __name__ == "__main__":
    main()
