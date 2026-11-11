"""Basic commands: /start, /help, /ping, /id, /annulla (follow-up questions, see prompts)."""

from __future__ import annotations

import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from homegram import prompts, strings
from homegram.context import get_ctx, thread_id_of
from homegram.features.base import Feature
from homegram.integrations.homeassistant import HomeAssistantError


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = get_ctx(context)
    message = update.effective_message
    lines = [
        f"/{cmd} — {html.escape(desc)}"
        for feature in ctx.features
        for cmd, desc in feature.commands
    ]
    text = strings.START.format(bot_name=strings.BOT_NAME, commands="\n".join(lines))

    chat = update.effective_chat
    if chat is not None and chat.type != chat.PRIVATE:
        bound = await ctx.bindings.features_for(chat.id, thread_id_of(message))
        if bound:
            text += strings.HELP_TOPIC_FEATURES.format(features=", ".join(bound))
            for feature in ctx.features:
                if feature.name in bound and feature.topic_hint:
                    text += strings.HELP_TOPIC_HINT.format(hint=html.escape(feature.topic_hint))

    await message.reply_text(text, parse_mode=ParseMode.HTML)


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = get_ctx(context)
    db_ok = await ctx.db.healthcheck()
    lines = [
        strings.PING_OK,
        strings.PING_DB.format(status=strings.STATUS_OK if db_ok else strings.STATUS_KO),
    ]
    if ctx.ha is not None:
        try:
            ha_ok = await ctx.ha.ping()
        except HomeAssistantError:
            ha_ok = False
        lines.append(
            strings.PING_HA.format(status=strings.STATUS_OK if ha_ok else strings.STATUS_KO)
        )
    await update.effective_message.reply_text("\n".join(lines))


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    await message.reply_text(
        strings.ID_INFO.format(
            chat_id=message.chat_id,
            thread_id=thread_id_of(message),
            user_id=user.id if user else "-",
        ),
        parse_mode=ParseMode.HTML,
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler(["start", "help"], help_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("id", id_command))
    prompts.register(app)


FEATURE = Feature(
    name="core",
    description="Comandi di base",
    register=register,
    commands=[
        ("help", "mostra questo messaggio"),
        ("ping", "controlla che il bot funzioni"),
        ("id", "mostra gli id di chat, topic e utente"),
        (prompts.CANCEL_COMMAND, "annulla la domanda in corso"),
    ],
)
