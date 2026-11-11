"""Waste collection: /bidoni (next pickups) and the reminder the evening before.

The reminder goes to the topics bound with ``/bind bidoni`` at WASTE_REMINDER_TIME when
something is collected tomorrow, with "Fatto" / "Non serve" buttons. If nobody taps them it
is repeated at WASTE_REPEAT_TIME.

Pickups come from the sensors of the waste_collection_schedule integration: their
attributes map dates ("2026-11-13") to waste types ("Vpl").
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from homegram import notify, strings
from homegram.context import CTX_KEY, AppContext, get_ctx
from homegram.db.repositories import GLOBAL_CHAT
from homegram.features.base import Feature
from homegram.integrations.ha_events import time_trigger
from homegram.integrations.homeassistant import HomeAssistantError

log = logging.getLogger(__name__)

FEATURE_NAME = "bidoni"
CALLBACK_PREFIX = "bid"
REMINDER_KEY = "bidoni.reminder"
INTEGRATION = "waste_collection_schedule"
UPCOMING_DAYS = 14

# Waste type (as in the sensors) -> (emoji, label, "metti fuori ..." wording).
TYPES: dict[str, tuple[str, str, str]] = {
    "carta": ("🟡", "Carta", "la carta"),
    "secco": ("⚫", "Secco", "il secco"),
    "umido": ("🟤", "Umido", "l'umido"),
    "vegetale": ("🟢", "Vegetale", "il vegetale"),
    "vpl": ("🔵", "Plastica", "la plastica"),
    "plastica": ("🔵", "Plastica", "la plastica"),
    "vetro": ("🟢", "Vetro", "il vetro"),
}
WEEKDAYS = ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom")


@dataclass(frozen=True)
class Waste:
    name: str  # as in the sensor, e.g. "Vpl"

    @property
    def _info(self) -> tuple[str, str, str]:
        return TYPES.get(self.name.lower(), ("🗑", self.name, self.name.lower()))

    @property
    def label(self) -> str:
        emoji, label, _ = self._info
        return f"{emoji} {label}"

    @property
    def phrase(self) -> str:
        return self._info[2]


def pickups(states: dict[str, dict[str, Any]], sensors: list[str]) -> dict[date, list[Waste]]:
    """Every scheduled pickup, by day."""
    out: dict[date, list[Waste]] = {}
    for entity_id in sensors:
        attributes = (states.get(entity_id) or {}).get("attributes") or {}
        for key, value in attributes.items():
            try:
                day = date.fromisoformat(str(key))
            except ValueError:
                continue
            waste = Waste(str(value))
            if waste not in out.setdefault(day, []):
                out[day].append(waste)
    return dict(sorted(out.items()))


async def load(ctx: AppContext) -> tuple[date, dict[date, list[Waste]]]:
    """Today (HA's time zone) and the pickups."""
    assert ctx.ha is not None
    sensors = list(ctx.settings.ha_waste_sensors)
    if not sensors:
        found = await ctx.ha.render_template(
            "{{ integration_entities('" + INTEGRATION + "') | select('match', 'sensor[.]') "
            "| list | tojson }}"
        )
        sensors = json.loads(found)
    today = (await ctx.ha.now()).date()
    return today, pickups(await ctx.ha.states(), sensors)


def day_label(day: date, today: date) -> str:
    text = f"{WEEKDAYS[day.weekday()]} {day.day}/{day.month}"
    if day == today:
        text += strings.WASTE_TODAY
    elif day == today + timedelta(days=1):
        text += strings.WASTE_TOMORROW
    return text


def render_upcoming(today: date, schedule: dict[date, list[Waste]]) -> str:
    days = [d for d in schedule if today <= d < today + timedelta(days=UPCOMING_DAYS)]
    if not days:
        return strings.WASTE_NONE
    lines = [strings.WASTE_TITLE]
    for day in days:
        types = ", ".join(w.label for w in schedule[day])
        lines.append(f"<b>{day_label(day, today)}</b>: {types}")
    return "\n".join(lines)


def reminder_text(wastes: list[Waste], *, again: bool = False) -> str:
    title = " + ".join(w.label.upper() for w in wastes)
    phrases = [w.phrase for w in wastes]
    things = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " e " + phrases[-1]
    template = strings.WASTE_REMINDER_AGAIN if again else strings.WASTE_REMINDER
    return template.format(
        title=html.escape(title, quote=False), things=html.escape(things, quote=False)
    )


def reminder_markup(day: date) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    strings.WASTE_BTN_DONE, callback_data=f"{CALLBACK_PREFIX}:done:{day}"
                ),
                InlineKeyboardButton(
                    strings.WASTE_BTN_SKIP, callback_data=f"{CALLBACK_PREFIX}:skip:{day}"
                ),
            ]
        ]
    )


# --- reminder state (one evening at a time) ---------------------------------------------


async def _get_reminder(ctx: AppContext) -> dict[str, Any]:
    raw = await ctx.chat_settings.get(GLOBAL_CHAT, REMINDER_KEY)
    return json.loads(raw) if raw else {}


async def _set_reminder(ctx: AppContext, reminder: dict[str, Any]) -> None:
    await ctx.chat_settings.set(GLOBAL_CHAT, REMINDER_KEY, json.dumps(reminder))


async def send_reminder(app: Application, *, again: bool) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    today, schedule = await load(ctx)
    tomorrow = today + timedelta(days=1)
    wastes = schedule.get(tomorrow)
    if not wastes:
        return
    reminder = await _get_reminder(ctx)
    if reminder.get("day") != tomorrow.isoformat():
        if again:
            return  # the first reminder was not sent (e.g. bot offline): it will come tomorrow
        reminder = {"day": tomorrow.isoformat(), "messages": [], "done": ""}
    elif reminder.get("done") or not again:
        return  # already handled, or already sent this evening
    text = reminder_text(wastes, again=again)
    sent = await notify.to_feature(app.bot, ctx, FEATURE_NAME, text, reminder_markup(tomorrow))
    if not again:
        reminder["text"] = text
    reminder["messages"] += [[m.chat_id, m.message_id] for m in sent]
    await _set_reminder(ctx, reminder)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    ctx = get_ctx(context)
    _, action, day = [*(query.data or "").split(":", 2), "", ""][:3]
    reminder = await _get_reminder(ctx)
    if reminder.get("day") != day or action not in ("done", "skip"):
        await query.answer(strings.WASTE_OLD, show_alert=True)
        await query.edit_message_reply_markup(None)
        return
    who = html.escape(query.from_user.first_name if query.from_user else "")
    if not reminder.get("done"):
        template = strings.WASTE_DONE_BY if action == "done" else strings.WASTE_SKIPPED_BY
        reminder["done"] = template.format(who=who)
        await _set_reminder(ctx, reminder)
    await query.answer()
    # Update every reminder of the evening (all topics, first one and repetition).
    text = f"{reminder.get('text') or query.message.text_html}\n\n{reminder['done']}"
    for chat_id, message_id in reminder.get("messages") or []:
        try:
            await context.bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, parse_mode=ParseMode.HTML
            )
        except (BadRequest, TelegramError) as exc:
            log.debug("Could not update reminder %s/%s: %s", chat_id, message_id, exc)


async def bidoni_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        text = render_upcoming(*await load(get_ctx(context)))
    except HomeAssistantError:
        text = strings.HA_UNAVAILABLE
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def start(app: Application) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    if ctx.events is None:
        return
    events, settings = ctx.events, ctx.settings

    async def first(trigger: dict[str, Any]) -> None:
        await send_reminder(app, again=False)

    async def repeat(trigger: dict[str, Any]) -> None:
        await send_reminder(app, again=True)

    if settings.waste_reminder_time:
        trigger = time_trigger(settings.waste_reminder_time)
        await events.subscribe("bidoni.reminder", trigger, first)
    if settings.waste_repeat_time:
        await events.subscribe("bidoni.repeat", time_trigger(settings.waste_repeat_time), repeat)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("bidoni", bidoni_command))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=rf"^{CALLBACK_PREFIX}:"))


FEATURE = Feature(
    name=FEATURE_NAME,
    description="Raccolta differenziata",
    register=register,
    commands=[("bidoni", "prossimi ritiri della raccolta differenziata")],
    bindable=True,
    topic_hint=strings.WASTE_TOPIC_HINT,
    requires_homeassistant=True,
    start=start,
)
