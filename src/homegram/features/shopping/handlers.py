"""Shopping list: /spesa, /spesa_aggiungi, inline buttons and free-text adding in a bound topic."""

from __future__ import annotations

import html
import logging
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from homegram import prompts, strings
from homegram.context import get_ctx, thread_id_of
from homegram.features.base import Feature
from homegram.features.shopping.backends import ShoppingItem

log = logging.getLogger(__name__)

FEATURE_NAME = "spesa"
CALLBACK_PREFIX = "shop"
# chat_settings key holding the id of the latest list message, kept up to date in place.
LIVE_MESSAGE_KEY = "shopping.live_message"
ASK_ADD = "shopping.add"
# Handler group for free-text messages, so other features can also react to the same text.
TEXT_HANDLER_GROUP = 10

MAX_ITEM_LENGTH = 200
MAX_SHOWN = 30
BUTTON_LABEL_LENGTH = 40

_SEPARATORS = re.compile(r"[,;\n]+")
_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s*")


def parse_items(text: str | None) -> list[str]:
    """Split free text into list items: commas, semicolons and new lines separate items."""
    items = []
    for part in _SEPARATORS.split(text or ""):
        cleaned = _BULLET.sub("", part).strip()
        if cleaned:
            items.append(cleaned[:MAX_ITEM_LENGTH])
    return items


def _truncate(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def render_list(items: list[ShoppingItem]) -> tuple[str, InlineKeyboardMarkup]:
    shown = items[:MAX_SHOWN]
    if not items:
        text = strings.SHOP_EMPTY
    else:
        lines = [strings.SHOP_TITLE.format(count=len(items))]
        lines += [f"• {html.escape(_truncate(item.text, 100))}" for item in shown]
        if len(items) > len(shown):
            lines.append(strings.SHOP_MORE.format(count=len(items) - len(shown)))
        text = "\n".join(lines)

    rows = []
    for item in shown:
        data = f"{CALLBACK_PREFIX}:done:{item.id}"
        if len(data.encode()) <= 64:  # Telegram callback_data limit
            label = f"✅ {_truncate(item.text, BUTTON_LABEL_LENGTH)}"
            rows.append([InlineKeyboardButton(label, callback_data=data)])
    rows.append(
        [
            InlineKeyboardButton(
                strings.SHOP_BTN_REFRESH, callback_data=f"{CALLBACK_PREFIX}:refresh"
            ),
            InlineKeyboardButton(strings.SHOP_BTN_CLEAR, callback_data=f"{CALLBACK_PREFIX}:clear"),
        ]
    )
    return text, InlineKeyboardMarkup(rows)


def _is_not_modified(exc: BadRequest) -> bool:
    return "not modified" in str(exc).lower()


async def refresh_live_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Update the latest list message of the chat, if there is one."""
    ctx = get_ctx(context)
    raw = await ctx.chat_settings.get(chat_id, LIVE_MESSAGE_KEY)
    if not raw:
        return
    text, markup = render_list(await ctx.shopping.list_open(chat_id))
    try:
        await context.bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=int(raw),
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except BadRequest as exc:
        if not _is_not_modified(exc):
            log.info("Live list message %s in chat %s is gone: %s", raw, chat_id, exc)
            await ctx.chat_settings.delete(chat_id, LIVE_MESSAGE_KEY)


async def send_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = get_ctx(context)
    chat_id = update.effective_chat.id
    text, markup = render_list(await ctx.shopping.list_open(chat_id))
    sent = await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=markup
    )
    await ctx.chat_settings.set(chat_id, LIVE_MESSAGE_KEY, str(sent.message_id))


async def add_items(
    update: Update, context: ContextTypes.DEFAULT_TYPE, items: list[str], *, quiet: bool
) -> None:
    ctx = get_ctx(context)
    message = update.effective_message
    chat_id = update.effective_chat.id
    user = update.effective_user
    await ctx.shopping.add(chat_id, items, user.id if user else None)

    confirmed = False
    if quiet:
        try:
            await message.set_reaction("👍")
            confirmed = True
        except TelegramError:
            log.debug("Could not react to message, falling back to a reply", exc_info=True)
    if not confirmed:
        await message.reply_text(
            strings.SHOP_ADDED.format(items=html.escape(", ".join(items))),
            parse_mode=ParseMode.HTML,
        )
    await refresh_live_list(context, chat_id)


def _command_items(update: Update) -> list[str]:
    parts = (update.effective_message.text or "").split(maxsplit=1)
    return parse_items(parts[1]) if len(parts) > 1 else []


async def spesa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the list. With arguments it adds them (kept for `/spesa latte` habits)."""
    items = _command_items(update)
    if items:
        await add_items(update, context, items, quiet=False)
    else:
        await send_list(update, context)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _command_items(update)
    if items:
        await add_items(update, context, items, quiet=False)
    else:
        await prompts.ask(update, context, ASK_ADD, strings.SHOP_ASK_ADD)


async def answer_add(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, data: dict[str, Any]
) -> None:
    items = parse_items(text)
    if not items:
        await prompts.ask(update, context, ASK_ADD, strings.SHOP_ASK_ADD)
        return
    await add_items(update, context, items, quiet=False)


async def on_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """In a topic bound to the shopping list, every text message is added to the list."""
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or not message.text:
        return
    ctx = get_ctx(context)
    if FEATURE_NAME not in await ctx.bindings.features_for(chat.id, thread_id_of(message)):
        return
    items = parse_items(message.text)
    if items:
        await add_items(update, context, items, quiet=True)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    message = query.message
    if message is None or not query.data:
        await query.answer()
        return
    ctx = get_ctx(context)
    chat_id = message.chat.id
    _, action, *rest = query.data.split(":", 2)

    toast: str | None = None
    if action == "done" and rest:
        ok = await ctx.shopping.complete(chat_id, rest[0])
        toast = strings.SHOP_DONE if ok else strings.SHOP_NOT_FOUND
    elif action == "clear":
        removed = await ctx.shopping.clear_completed(chat_id)
        toast = (
            strings.SHOP_CLEARED_UNKNOWN
            if removed is None
            else strings.SHOP_CLEARED.format(count=removed)
        )
    await query.answer(toast)

    text, markup = render_list(await ctx.shopping.list_open(chat_id))
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as exc:
        if not _is_not_modified(exc):
            raise
    await ctx.chat_settings.set(chat_id, LIVE_MESSAGE_KEY, str(message.message_id))


def register(app: Application) -> None:
    app.add_handler(CommandHandler("spesa", spesa_command))
    app.add_handler(CommandHandler("spesa_aggiungi", add_command))
    # Old name of /spesa, kept as a hidden alias.
    app.add_handler(CommandHandler("lista", send_list))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=rf"^{CALLBACK_PREFIX}:"))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS & filters.UpdateType.MESSAGE,
            on_topic_text,
        ),
        group=TEXT_HANDLER_GROUP,
    )
    prompts.on_answer(ASK_ADD, answer_add)


FEATURE = Feature(
    name=FEATURE_NAME,
    description="Lista della spesa condivisa",
    register=register,
    commands=[
        ("spesa", "mostra la lista della spesa"),
        ("spesa_aggiungi", "aggiungi alla lista (es. /spesa_aggiungi latte, uova)"),
    ],
    bindable=True,
    topic_hint=strings.SHOP_TOPIC_HINT,
)
