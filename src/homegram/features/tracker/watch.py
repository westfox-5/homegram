"""Tracker notifications on Telegram: Home Assistant state changes -> bound topics.

Notifications go to every topic bound with ``/bind tracker``. Muted products are a bot-wide
setting; the first time they are imported from the old Home Assistant automation.

The same connection drives the refresh of the tracked pages (every `REFRESH_MINUTES`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from homegram import notify, strings
from homegram.context import CTX_KEY, AppContext
from homegram.db.repositories import GLOBAL_CHAT
from homegram.features.tracker.alerts import alert_for
from homegram.features.tracker.service import REFRESH_MINUTES
from homegram.integrations.homeassistant import HomeAssistantError

log = logging.getLogger(__name__)

FEATURE_NAME = "tracker"
MUTED_KEY = "tracker.muted"
SUBSCRIPTION = "tracker"
REFRESH_SUBSCRIPTION = "tracker_refresh"
REFRESH_TRIGGER = {"trigger": "time_pattern", "minutes": f"/{REFRESH_MINUTES}"}
NOTIFY_PREFIX = "trn"


async def muted_products(ctx: AppContext) -> set[str]:
    raw = await ctx.chat_settings.get(GLOBAL_CHAT, MUTED_KEY)
    if raw is not None:
        return set(json.loads(raw))
    imported = await _import_muted(ctx)
    if imported is not None:
        await set_muted_products(ctx, imported)
        return imported
    return set()


async def set_muted_products(ctx: AppContext, names: set[str]) -> None:
    await ctx.chat_settings.set(GLOBAL_CHAT, MUTED_KEY, json.dumps(sorted(names)))


async def _import_muted(ctx: AppContext) -> set[str] | None:
    """Muted products of the old HA automation; None if HA could not be asked (retry later)."""
    automation = ctx.settings.ha_tracker_automation
    if ctx.ha is None or not automation:
        return set()
    try:
        config = await ctx.ha.automation_config(automation)
    except HomeAssistantError:
        log.warning("Could not read the muted products of automation %s", automation)
        return None
    triggers = (config or {}).get("triggers") or (config or {}).get("trigger") or [{}]
    muted = (triggers[0].get("variables") or {}).get("muted") or []
    log.info("Imported %d muted tracker products from automation %s", len(muted), automation)
    return {m for m in muted if isinstance(m, str)}


def mute_markup(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    strings.TRACKER_BTN_MUTE, callback_data=f"{NOTIFY_PREFIX}:mute:{entry_id}"
                )
            ]
        ]
    )


async def on_trigger(app: Application, trigger: dict[str, Any]) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    assert ctx.tracker is not None
    entity_id = (trigger.get("to_state") or {}).get("entity_id")
    link = next(
        (
            link
            for product in await ctx.tracker.products()
            for link in product.links
            if entity_id in link.entities.values()
        ),
        None,
    )
    alert = alert_for(trigger, await muted_products(ctx), link.url if link else None)
    if alert is None:
        return
    markup = mute_markup(link.entry_id) if link else None
    await notify.to_feature(app.bot, ctx, FEATURE_NAME, alert.text, markup)


async def start(app: Application) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    if ctx.tracker is None or ctx.events is None:
        return
    events, tracker = ctx.events, ctx.tracker

    async def callback(trigger: dict[str, Any]) -> None:
        await on_trigger(app, trigger)

    async def refresh() -> None:
        entities = await tracker.entities()
        # `to: null`: state changes only, not attribute updates.
        trigger = {"trigger": "state", "entity_id": entities, "to": None} if entities else []
        await events.subscribe(SUBSCRIPTION, trigger, callback)

    async def scrape(_trigger: dict[str, Any]) -> None:
        await tracker.refresh()

    tasks: set[asyncio.Task[None]] = set()

    async def configure_entries() -> None:
        try:
            await tracker.configure_entries()
        except Exception:
            log.warning("Could not configure the tracker's scrape entries", exc_info=True)

    async def configure() -> None:
        # In the background: it may take a while and must not delay the subscriptions.
        task = asyncio.create_task(configure_entries())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    events.on_connect(refresh)  # also picks up sensors added or renamed in HA
    events.on_connect(configure)  # entries added by hand in HA, or by older versions
    tracker.on_change(refresh)
    await events.subscribe(REFRESH_SUBSCRIPTION, REFRESH_TRIGGER, scrape)
