"""Attach features to forum topics: /bind, /unbind, /bindings."""

from __future__ import annotations

import html

from telegram import Chat, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from homegram import strings
from homegram.context import AppContext, get_ctx, thread_id_of
from homegram.features.base import Feature


def _bindable(ctx: AppContext) -> list[str]:
    return [f.name for f in ctx.features if f.bindable]


def topic_link(chat_id: int, thread_id: int) -> str | None:
    """Public t.me link to a topic of a supergroup (works for members only)."""
    raw = str(chat_id)
    if not raw.startswith("-100") or not thread_id:
        return None
    return f"https://t.me/c/{raw[4:]}/{thread_id}"


async def _parse(
    update: Update, context: ContextTypes.DEFAULT_TYPE, usage: str
) -> tuple[AppContext, Chat, int, str] | None:
    ctx = get_ctx(context)
    message = update.effective_message
    chat = update.effective_chat
    available = ", ".join(_bindable(ctx))

    if chat.type == Chat.PRIVATE:
        await message.reply_text(strings.BIND_ONLY_GROUPS)
        return None
    if not context.args:
        await message.reply_text(usage.format(features=available), parse_mode=ParseMode.HTML)
        return None
    feature = context.args[0].lower()
    if feature not in _bindable(ctx):
        await message.reply_text(
            strings.BIND_UNKNOWN.format(feature=html.escape(feature), features=available),
            parse_mode=ParseMode.HTML,
        )
        return None
    return ctx, chat, thread_id_of(message), feature


async def bind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parsed = await _parse(update, context, strings.BIND_USAGE)
    if parsed is None:
        return
    ctx, chat, thread_id, feature = parsed
    user = update.effective_user
    created = await ctx.bindings.bind(chat.id, thread_id, feature, user.id if user else None)
    text = strings.BIND_OK if created else strings.BIND_ALREADY
    hint = next((f.topic_hint for f in ctx.features if f.name == feature), "")
    if created and hint:
        text += f"\n<i>{html.escape(hint)}</i>"
    await update.effective_message.reply_text(
        text.format(feature=feature), parse_mode=ParseMode.HTML
    )


async def unbind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parsed = await _parse(update, context, strings.UNBIND_USAGE)
    if parsed is None:
        return
    ctx, chat, thread_id, feature = parsed
    removed = await ctx.bindings.unbind(chat.id, thread_id, feature)
    text = strings.UNBIND_OK if removed else strings.UNBIND_MISSING
    await update.effective_message.reply_text(
        text.format(feature=feature), parse_mode=ParseMode.HTML
    )


async def bindings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = get_ctx(context)
    chat = update.effective_chat
    bindings = await ctx.bindings.for_chat(chat.id)
    if not bindings:
        await update.effective_message.reply_text(strings.BINDINGS_EMPTY, parse_mode=ParseMode.HTML)
        return
    lines = [strings.BINDINGS_HEADER]
    for b in bindings:
        if b.thread_id == 0:
            where = strings.BINDINGS_GENERAL
        else:
            where = strings.BINDINGS_TOPIC.format(thread_id=b.thread_id)
            link = topic_link(b.chat_id, b.thread_id)
            if link:
                where = f'<a href="{link}">{where}</a>'
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
