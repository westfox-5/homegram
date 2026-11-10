"""Shared application context available to every feature handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telegram import Message
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    from homegram.config import Settings
    from homegram.db import ChatSettingsRepo, Database, TopicBindingRepo
    from homegram.features.base import Feature
    from homegram.features.shopping.backends import ShoppingBackend
    from homegram.features.tracker.service import TrackerService
    from homegram.integrations.homeassistant import HomeAssistantClient

CTX_KEY = "homegram"


@dataclass
class AppContext:
    settings: Settings
    db: Database
    bindings: TopicBindingRepo
    chat_settings: ChatSettingsRepo
    shopping: ShoppingBackend
    features: list[Feature]
    ha: HomeAssistantClient | None = None
    tracker: TrackerService | None = None


def get_ctx(context: ContextTypes.DEFAULT_TYPE) -> AppContext:
    return context.application.bot_data[CTX_KEY]


def thread_id_of(message: Message) -> int:
    """Forum topic id of a message, or 0 for the main chat / General topic."""
    if message.is_topic_message and message.message_thread_id:
        return message.message_thread_id
    return 0
