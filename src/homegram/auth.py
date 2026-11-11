"""Whitelist guard, run before every other handler."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from homegram import strings
from homegram.config import Settings

log = logging.getLogger(__name__)

# Commands anyone may use, so new users can find out the ids to whitelist.
PUBLIC_COMMANDS = frozenset({"id"})

SETTINGS_KEY = "settings"
# Handler group of the guard: before everything else (follow-up questions run in -1).
GROUP = -2


def is_allowed(settings: Settings, user_id: int | None, chat_id: int | None) -> bool:
    """An update is allowed when its user or its chat is whitelisted."""
    if user_id is not None and user_id in settings.allowed_user_ids:
        return True
    return chat_id is not None and chat_id in settings.allowed_chat_ids


def command_name(text: str | None) -> str | None:
    if not text or not text.startswith("/"):
        return None
    return text.split(maxsplit=1)[0][1:].split("@", 1)[0].lower()


async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data[SETTINGS_KEY]
    user = update.effective_user
    chat = update.effective_chat
    if is_allowed(settings, user.id if user else None, chat.id if chat else None):
        return

    message = update.effective_message
    if message is not None and command_name(message.text) in PUBLIC_COMMANDS:
        return

    log.warning(
        "Ignoring update from unauthorized user=%s chat=%s",
        user.id if user else None,
        chat.id if chat else None,
    )
    if update.callback_query is not None:
        await update.callback_query.answer(strings.NOT_ALLOWED, show_alert=True)
    raise ApplicationHandlerStop
