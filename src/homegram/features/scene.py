"""Scenes: /scene shows a button for each Home Assistant scene or script and runs it.

The list is HA_SCENES, or else every `scene.*` plus every script without input fields
(scripts with fields, like a notification helper, need data and are not scenes).
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from homegram import strings
from homegram.context import AppContext, get_ctx
from homegram.features.base import Feature
from homegram.integrations.homeassistant import HomeAssistantError

log = logging.getLogger(__name__)

FEATURE_NAME = "scene"
CALLBACK_PREFIX = "scn"
LABEL_LENGTH = 24

# mdi icon fragments -> emoji, first match wins.
_ICONS = (
    ("night", "🌙"),
    ("sleep", "🛏"),
    ("bed", "🛏"),
    ("sunset", "🌆"),
    ("sunrise", "🌅"),
    ("movie", "🎬"),
    ("television", "📺"),
    ("tv", "📺"),
    ("vacuum", "🧹"),
    ("broom", "🧹"),
    ("lock-open", "🏠"),
    ("clock", "🚪"),
    ("door", "🚪"),
    ("home", "🏠"),
    ("light", "💡"),
    ("lamp", "💡"),
    ("sun", "☀️"),
    ("music", "🎵"),
)


@dataclass(frozen=True)
class Scene:
    entity_id: str
    name: str
    icon: str = ""

    @property
    def emoji(self) -> str:
        icon = self.icon.lower()
        return next((emoji for fragment, emoji in _ICONS if fragment in icon), "▶️")

    @property
    def label(self) -> str:
        name = self.name if len(self.name) <= LABEL_LENGTH else self.name[: LABEL_LENGTH - 1] + "…"
        return f"{self.emoji} {name}"


async def load_scenes(ctx: AppContext) -> list[Scene]:
    assert ctx.ha is not None
    states = await ctx.ha.states()
    wanted = list(ctx.settings.ha_scenes)
    if not wanted:
        for entity_id in sorted(states):
            if entity_id.startswith("scene."):
                wanted.append(entity_id)
            elif entity_id.startswith("script."):
                config = await ctx.ha.script_config(entity_id.removeprefix("script."))
                if not (config or {}).get("fields"):
                    wanted.append(entity_id)
    scenes = []
    for entity_id in wanted:
        state = states.get(entity_id)
        if state is None:
            log.warning("Scene %s not found in Home Assistant", entity_id)
            continue
        attributes = state.get("attributes") or {}
        name = attributes.get("friendly_name") or entity_id.split(".", 1)[-1]
        scenes.append(Scene(entity_id, str(name), str(attributes.get("icon") or "")))
    return scenes


def render(scenes: list[Scene], last: str = "") -> tuple[str, InlineKeyboardMarkup | None]:
    if not scenes:
        return strings.SCENE_EMPTY, None
    buttons = [
        InlineKeyboardButton(s.label, callback_data=f"{CALLBACK_PREFIX}:run:{s.entity_id}")
        for s in scenes
        if len(f"{CALLBACK_PREFIX}:run:{s.entity_id}".encode()) <= 64
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    text = strings.SCENE_TITLE + (f"\n\n{last}" if last else "")
    return text, InlineKeyboardMarkup(rows)


async def scene_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = get_ctx(context)
    try:
        scenes = await load_scenes(ctx)
    except HomeAssistantError:
        await update.effective_message.reply_text(strings.HA_UNAVAILABLE, parse_mode=ParseMode.HTML)
        return
    text, markup = render(scenes)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.message is None or not query.data:
        await query.answer()
        return
    ctx = get_ctx(context)
    assert ctx.ha is not None
    entity_id = query.data.split(":", 2)[-1]
    domain = entity_id.split(".", 1)[0]
    try:
        scenes = await load_scenes(ctx)
        scene = next((s for s in scenes if s.entity_id == entity_id), None)
        if scene is None or domain not in ("scene", "script"):
            await query.answer(strings.SCENE_GONE, show_alert=True)
            return
        # script.turn_on returns right away, without waiting for the script to end.
        await ctx.ha.call_service(domain, "turn_on", {"entity_id": entity_id})
    except HomeAssistantError as exc:
        log.warning("Could not run %s: %s", entity_id, exc)
        await query.answer(strings.SCENE_FAILED, show_alert=True)
        return
    await query.answer(strings.SCENE_STARTED.format(scene=scene.name))
    who = query.from_user.first_name if query.from_user else ""
    try:
        when = (await ctx.ha.now()).strftime("%H:%M")  # HA's time zone, not the container's
    except HomeAssistantError:
        when = ""
    last = strings.SCENE_LAST.format(
        scene=html.escape(scene.label), who=html.escape(who), time=when
    )
    text, markup = render(scenes, last)
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def register(app: Application) -> None:
    app.add_handler(CommandHandler("scene", scene_command))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=rf"^{CALLBACK_PREFIX}:"))


FEATURE = Feature(
    name=FEATURE_NAME,
    description="Scene e script di Home Assistant",
    register=register,
    commands=[("scene", "lancia una scena (Esco, Entro, Sera, …)")],
    bindable=True,
    topic_hint=strings.SCENE_TOPIC_HINT,
    requires_homeassistant=True,
)
