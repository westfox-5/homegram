"""Feature contract: each feature is a self-contained module that registers its handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from telegram.ext import Application


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
