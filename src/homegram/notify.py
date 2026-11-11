"""Post a feature's notifications to the topics bound to it (/bind <feature>)."""

from __future__ import annotations

import logging

from telegram import Bot, InlineKeyboardMarkup, LinkPreviewOptions, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError

from homegram.context import AppContext

log = logging.getLogger(__name__)


async def to_feature(
    bot: Bot,
    ctx: AppContext,
    feature: str,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> list[Message]:
    """Send `text` (HTML) to every topic bound to `feature`. Returns the messages sent.

    Nobody is notified when the feature is not bound anywhere.
    """
    sent = []
    for binding in await ctx.bindings.for_feature(feature):
        try:
            sent.append(
                await bot.send_message(
                    binding.chat_id,
                    text,
                    message_thread_id=binding.thread_id or None,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            )
        except TelegramError:
            log.warning(
                "Could not notify %s in chat %s topic %s",
                feature,
                binding.chat_id,
                binding.thread_id,
                exc_info=True,
            )
    if not sent:
        log.info("Nothing to notify for %s: not bound to any topic", feature)
    return sent
