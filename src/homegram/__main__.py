"""Entrypoint: `python -m homegram` or the `homegram` script."""

from __future__ import annotations

import logging

from telegram import Update

from homegram.bot import build_application
from homegram.config import Settings


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app = build_application(settings)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
