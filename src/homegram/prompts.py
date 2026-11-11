"""Follow-up questions: a command run without its arguments asks for them.

`ask` sends a question and remembers it for the user in that chat/topic; the next text
message of the same user there is the answer, handed to the handler registered with
`on_answer`. Any other command, the cancel button or /annulla drop the question, and it
expires after `TTL` seconds.

The handlers run in `GROUP`, right after the whitelist guard and before every feature, so
an answer is not also taken as free text (e.g. added to the shopping list in a bound topic).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from homegram import strings
from homegram.context import thread_id_of

log = logging.getLogger(__name__)

GROUP = -1
TTL = 600  # seconds
CALLBACK_CANCEL = "prm:cancel"
CANCEL_COMMAND = "annulla"
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

AnswerHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE, str, dict[str, Any]], Awaitable[None]]
Rows = Sequence[Sequence[InlineKeyboardButton]]

_HANDLERS: dict[str, AnswerHandler] = {}


@dataclass(frozen=True)
class Pending:
    key: str
    data: dict[str, Any]
    asked_at: float


def on_answer(key: str, handler: AnswerHandler) -> None:
    """Register the handler of the answers to the questions asked with `key`."""
    _HANDLERS[key] = handler


def _slot(user_id: int, thread_id: int) -> str:
    return f"prompt:{user_id}:{thread_id}"


def _where(update: Update) -> tuple[int, int] | None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return None
    return user.id, thread_id_of(message)


def set_pending(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, **data: Any) -> None:
    where = _where(update)
    if where is None or context.chat_data is None:
        return
    context.chat_data[_slot(*where)] = Pending(key, data, time.monotonic())


def pop_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Pending | None:
    """Take the question waiting for this user here, if any and not expired."""
    where = _where(update)
    if where is None or context.chat_data is None:
        return None
    pending = context.chat_data.pop(_slot(*where), None)
    if not isinstance(pending, Pending) or time.monotonic() - pending.asked_at > TTL:
        return None
    return pending


def cancel_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(strings.PROMPT_BTN_CANCEL, callback_data=CALLBACK_CANCEL)


def with_cancel(rows: Rows = ()) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([*[list(row) for row in rows], [cancel_button()]])


async def ask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    key: str,
    text: str,
    rows: Rows = (),
    *,
    edit: bool = False,
    **data: Any,
) -> None:
    """Ask `text` (HTML) and wait for the user's next text message.

    `rows` are extra inline buttons shown above the cancel button. With `edit`, the message
    of the tapped inline button is replaced instead of sending a new one.
    """
    set_pending(update, context, key, **data)
    markup = with_cancel(rows)
    query = update.callback_query
    if edit and query is not None:
        try:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                link_preview_options=NO_PREVIEW,
            )
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise
        return
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=markup, link_preview_options=NO_PREVIEW
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return
    pending = pop_pending(update, context)
    if pending is None:
        return
    handler = _HANDLERS.get(pending.key)
    if handler is None:
        log.warning("No handler for the answers to %r", pending.key)
        return
    try:
        await handler(update, context, message.text.strip(), pending.data)
    except ApplicationHandlerStop:
        raise
    except Exception as exc:
        await context.application.process_error(update, exc)
    raise ApplicationHandlerStop  # the message was an answer: nobody else handles it


async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Another command drops the pending question (the command itself runs normally)."""
    pop_pending(update, context)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = pop_pending(update, context)
    await update.effective_message.reply_text(
        strings.PROMPT_CANCELLED if pending else strings.PROMPT_NOTHING
    )
    raise ApplicationHandlerStop


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    pop_pending(update, context)
    await query.answer()
    if query.message is not None:
        try:
            await query.edit_message_text(strings.PROMPT_CANCELLED)
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise


def register(app: Application) -> None:
    # Within a group only the first matching handler runs: /annulla before other commands.
    app.add_handler(CommandHandler(CANCEL_COMMAND, cancel_command), group=GROUP)
    app.add_handler(
        MessageHandler(filters.COMMAND & filters.UpdateType.MESSAGE, on_command), group=GROUP
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, on_text),
        group=GROUP,
    )
    app.add_handler(CallbackQueryHandler(on_cancel, pattern=rf"^{CALLBACK_CANCEL}$"))
