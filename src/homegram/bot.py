"""Application wiring: database lifecycle, auth guard, features, error handling."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, ContextTypes, TypeHandler

from homegram import auth, prompts, strings
from homegram.config import Settings
from homegram.context import CTX_KEY, AppContext
from homegram.db import ChatSettingsRepo, Database, TopicBindingRepo
from homegram.features import enabled_features
from homegram.features.shopping.backends import (
    HomeAssistantShoppingBackend,
    ShoppingBackend,
    SqliteShoppingBackend,
)
from homegram.features.tracker.service import TrackerService
from homegram.integrations.ha_events import HomeAssistantEvents
from homegram.integrations.homeassistant import HomeAssistantClient, HomeAssistantError

log = logging.getLogger(__name__)

EVENTS_TASK_KEY = "ha_events_task"


async def _post_init(app: Application) -> None:
    settings: Settings = app.bot_data[auth.SETTINGS_KEY]

    db = Database(settings.database_path)
    await db.connect()

    ha: HomeAssistantClient | None = None
    events: HomeAssistantEvents | None = None
    if settings.homeassistant_enabled:
        ha = HomeAssistantClient(settings.ha_url, settings.ha_token)  # type: ignore[arg-type]
        events = HomeAssistantEvents(settings.ha_url, settings.ha_token)  # type: ignore[arg-type]

    shopping: ShoppingBackend
    if settings.shopping_backend == "homeassistant" and ha is not None:
        shopping = HomeAssistantShoppingBackend(ha, settings.ha_shopping_entity)
    else:
        shopping = SqliteShoppingBackend(db)

    features = enabled_features(settings)
    tracker = TrackerService(ha, events) if ha else None

    app.bot_data[CTX_KEY] = AppContext(
        settings=settings,
        db=db,
        bindings=TopicBindingRepo(db),
        chat_settings=ChatSettingsRepo(db),
        shopping=shopping,
        features=features,
        ha=ha,
        tracker=tracker,
        events=events,
    )

    if events is not None:
        # Features register their Home Assistant triggers, then the connection starts.
        for feature in features:
            if feature.start is not None:
                try:
                    await feature.start(app)
                except Exception:
                    log.exception("Could not start the notifications of %s", feature.name)
        app.bot_data[EVENTS_TASK_KEY] = asyncio.create_task(events.run())

    commands = [BotCommand(cmd, desc) for f in features for cmd, desc in f.commands]
    await app.bot.set_my_commands(commands)

    if not settings.allowed_user_ids and not settings.allowed_chat_ids:
        log.warning(
            "ALLOWED_USER_IDS and ALLOWED_CHAT_IDS are empty: the bot will ignore everyone. "
            "Send /id to the bot to find the ids to allow."
        )
    me = await app.bot.get_me()
    app.bot_data[prompts.READS_ALL_KEY] = bool(me.can_read_all_group_messages)
    log.info(
        "HomeGram started as @%s (shopping backend: %s)", me.username, settings.shopping_backend
    )
    if not me.can_read_all_group_messages:
        log.warning(
            "Privacy mode is on: in groups the bot only sees commands and replies to its own "
            "messages (unless it is an admin). Answers to its questions must be replies, and "
            "free text in bound topics is ignored. Turn it off with @BotFather → /setprivacy "
            "→ Disable, then remove and re-add the bot to the group, or make it an admin."
        )


async def _post_shutdown(app: Application) -> None:
    ctx: AppContext | None = app.bot_data.get(CTX_KEY)
    if ctx is None:
        return
    task: asyncio.Task[None] | None = app.bot_data.pop(EVENTS_TASK_KEY, None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    if ctx.events is not None:
        await ctx.events.close()
    if ctx.ha is not None:
        await ctx.ha.close()
    await ctx.db.close()


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    ha_error = isinstance(error, HomeAssistantError)
    if ha_error:
        log.warning("Home Assistant error: %s", error)
    else:
        log.error("Unhandled error while processing an update", exc_info=error)

    if not isinstance(update, Update):
        return
    text = strings.HA_UNAVAILABLE if ha_error else strings.GENERIC_ERROR
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(text, show_alert=True)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        log.debug("Could not notify the user about the error", exc_info=True)


def build_application(settings: Settings) -> Application:
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data[auth.SETTINGS_KEY] = settings
    app.add_handler(TypeHandler(Update, auth.guard), group=auth.GROUP)
    for feature in enabled_features(settings):
        feature.register(app)
    app.add_error_handler(_on_error)
    return app
