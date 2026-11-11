"""Attach features to forum topics: /bind, /unbind, /bindings."""

from __future__ import annotations

import html

from telegram import (
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from homegram import prompts, strings
from homegram.context import AppContext, get_ctx, thread_id_of
from homegram.db import TopicBindingRepo
from homegram.features.base import Feature

# After every feature: only learns topic names, never stops other handlers.
TOPIC_NAME_GROUP = 50


def _bindable(ctx: AppContext) -> list[str]:
    return [f.name for f in ctx.features if f.bindable]


def topic_link(chat_id: int, thread_id: int) -> str | None:
    """Public t.me link to a topic of a supergroup (works for members only)."""
    raw = str(chat_id)
    if not raw.startswith("-100") or not thread_id:
        return None
    return f"https://t.me/c/{raw[4:]}/{thread_id}"


def topic_name_of(message: Message | None) -> str | None:
    """The topic's name, when the message carries it.

    A message sent in a topic (not as a reply to another message) replies to the topic's
    creation message, which has the name; renaming a topic sends a service message.
    """
    if message is None:
        return None
    if message.forum_topic_created:
        return message.forum_topic_created.name
    if message.forum_topic_edited and message.forum_topic_edited.name:
        return message.forum_topic_edited.name
    reply = message.reply_to_message
    if message.is_topic_message and reply is not None and reply.forum_topic_created:
        return reply.forum_topic_created.name
    return None


async def remember_topic_name(bindings: TopicBindingRepo, message: Message | None) -> None:
    name = topic_name_of(message)
    if message is not None and name and message.message_thread_id:
        await bindings.set_topic_name(message.chat_id, message.message_thread_id, name)


async def topic_label(bindings: TopicBindingRepo, chat_id: int, thread_id: int) -> str:
    """HTML label of a topic: its name (or number), linked to it when possible."""
    if thread_id == 0:
        return strings.BINDINGS_GENERAL
    name = await bindings.topic_name(chat_id, thread_id)
    label = html.escape(name) if name else strings.BINDINGS_TOPIC.format(thread_id=thread_id)
    link = topic_link(chat_id, thread_id)
    return f'<a href="{link}">{label}</a>' if link else label


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await remember_topic_name(get_ctx(context).bindings, update.effective_message)


CALLBACK_PREFIX = "tpc"


def _feature_buttons(action: str, features: list[str]) -> InlineKeyboardMarkup:
    """One button per feature (+ cancel): tapping it binds / unbinds the current topic."""
    rows = [
        [InlineKeyboardButton(f, callback_data=f"{CALLBACK_PREFIX}:{action}:{f}")] for f in features
    ]
    return prompts.with_cancel(rows)


async def _bind(
    ctx: AppContext, chat_id: int, thread_id: int, feature: str, user_id: int | None
) -> str:
    created = await ctx.bindings.bind(chat_id, thread_id, feature, user_id)
    text = strings.BIND_OK if created else strings.BIND_ALREADY
    hint = next((f.topic_hint for f in ctx.features if f.name == feature), "")
    if created and hint:
        text += f"\n<i>{html.escape(hint)}</i>"
    return text.format(feature=feature)


async def _unbind(ctx: AppContext, chat_id: int, thread_id: int, feature: str) -> str:
    removed = await ctx.bindings.unbind(chat_id, thread_id, feature)
    return (strings.UNBIND_OK if removed else strings.UNBIND_MISSING).format(feature=feature)


async def _parse(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> tuple[AppContext, Chat, int, str] | None:
    """The feature argument; without it, reply with a button for each possible feature."""
    ctx = get_ctx(context)
    message = update.effective_message
    chat = update.effective_chat
    thread_id = thread_id_of(message)
    available = ", ".join(_bindable(ctx))

    if chat.type == Chat.PRIVATE:
        await message.reply_text(strings.BIND_ONLY_GROUPS)
        return None
    if not context.args:
        if action == "bind":
            text, features = strings.BIND_ASK, _bindable(ctx)
        else:
            text, features = strings.UNBIND_ASK, await ctx.bindings.features_for(chat.id, thread_id)
            if not features:
                await message.reply_text(strings.UNBIND_NONE)
                return None
        await message.reply_text(text, reply_markup=_feature_buttons(action, features))
        return None
    feature = context.args[0].lower()
    if feature not in _bindable(ctx):
        await message.reply_text(
            strings.BIND_UNKNOWN.format(feature=html.escape(feature), features=available),
            parse_mode=ParseMode.HTML,
        )
        return None
    return ctx, chat, thread_id, feature


async def bind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parsed = await _parse(update, context, "bind")
    if parsed is None:
        return
    ctx, chat, thread_id, feature = parsed
    user = update.effective_user
    text = await _bind(ctx, chat.id, thread_id, feature, user.id if user else None)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def unbind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parsed = await _parse(update, context, "unbind")
    if parsed is None:
        return
    ctx, chat, thread_id, feature = parsed
    text = await _unbind(ctx, chat.id, thread_id, feature)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    message = query.message
    if message is None or not query.data:
        await query.answer()
        return
    ctx = get_ctx(context)
    _, action, *rest = query.data.split(":", 2)
    feature = rest[0] if rest else ""
    if feature not in _bindable(ctx):
        await query.answer()
        return
    chat_id, thread_id = message.chat.id, thread_id_of(message)
    if action == "bind":
        text = await _bind(ctx, chat_id, thread_id, feature, query.from_user.id)
    else:
        text = await _unbind(ctx, chat_id, thread_id, feature)
    await query.answer()
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def bindings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = get_ctx(context)
    chat = update.effective_chat
    bindings = await ctx.bindings.for_chat(chat.id)
    if not bindings:
        await update.effective_message.reply_text(strings.BINDINGS_EMPTY, parse_mode=ParseMode.HTML)
        return
    lines = [strings.BINDINGS_HEADER]
    for b in bindings:
        where = await topic_label(ctx.bindings, b.chat_id, b.thread_id)
        lines.append(f"• <b>{b.feature}</b> → {where}")
    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("bind", bind_command))
    app.add_handler(CommandHandler("unbind", unbind_command))
    app.add_handler(CommandHandler("bindings", bindings_command))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=rf"^{CALLBACK_PREFIX}:"))
    app.add_handler(
        MessageHandler(filters.ChatType.SUPERGROUP & filters.UpdateType.MESSAGE, on_message),
        group=TOPIC_NAME_GROUP,
    )


FEATURE = Feature(
    name="topics",
    description="Collega le funzioni ai topic del gruppo",
    register=register,
    commands=[
        ("bind", "collega una funzione al topic corrente"),
        ("unbind", "scollega una funzione dal topic corrente"),
        ("bindings", "elenca i topic collegati"),
    ],
)
