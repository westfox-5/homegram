"""Feature contract: each feature is a self-contained module that registers its handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from telegram.ext import Application

if TYPE_CHECKING:
    from homegram.config import Settings


@dataclass(frozen=True)
class Feature:
    name: str
    description: str
    register: Callable[[Application], None]
    # (command, description) pairs, shown in /help and in Telegram's command menu.
    commands: list[tuple[str, str]] = field(default_factory=list)
    # Whether the feature can be attached to a forum topic with /bind.
    bindable: bool = False
    # Shown in /help inside a topic bound to this feature.
    topic_hint: str = ""
    # Only enabled when Home Assistant is configured (HA_URL and HA_TOKEN).
    requires_homeassistant: bool = False
    # Extra condition on the configuration (e.g. the entities it needs are set).
    available: Callable[[Settings], bool] | None = None
    # Run once at startup, after the app context exists: subscribe to Home Assistant events.
    start: Callable[[Application], Awaitable[None]] | None = None
