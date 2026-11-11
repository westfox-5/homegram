"""Energy: /energia (solar, house, battery, grid now and today) and notifications.

Notifications go to the topics bound with ``/bind energia``:
- surplus: exporting more than ENERGY_SURPLUS_KW for 10 minutes, at most once a day;
- daily report at ENERGY_REPORT_TIME: today's totals and tomorrow's solar forecast.

Sensors come from the ENERGY_* settings; missing ones are simply left out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from homegram import notify, strings
from homegram.config import Settings
from homegram.context import CTX_KEY, AppContext, get_ctx
from homegram.db.repositories import GLOBAL_CHAT
from homegram.features.base import Feature
from homegram.integrations.ha_events import time_trigger
from homegram.integrations.homeassistant import HomeAssistantError

log = logging.getLogger(__name__)

FEATURE_NAME = "energia"
SURPLUS_KEY = "energia.surplus_date"
GOOD_DAY_KWH = 8.0  # tomorrow's forecast above this: suggest running the appliances


def _decimal(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def kw(value: float) -> str:
    return f"{_decimal(value, 2)} kW"


def kwh(value: float) -> str:
    return f"{_decimal(value, 1)} kWh"


@dataclass
class Energy:
    """Values of the configured sensors, normalized to kW / kWh / %."""

    values: dict[str, float] = field(default_factory=dict)
    peak_tomorrow: str = ""  # HH:MM, Home Assistant's time zone

    def get(self, key: str) -> float | None:
        return self.values.get(key)


def read(sensors: dict[str, str], states: dict[str, dict[str, Any]], now: datetime) -> Energy:
    energy = Energy()
    for key, entity_id in sensors.items():
        state = states.get(entity_id) or {}
        raw = str(state.get("state", ""))
        if key == "peak_tomorrow":
            try:
                peak = datetime.fromisoformat(raw)
            except ValueError:
                continue
            energy.peak_tomorrow = peak.astimezone(now.tzinfo).strftime("%H:%M")
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = str((state.get("attributes") or {}).get("unit_of_measurement") or "")
        if unit in ("W", "Wh"):
            value /= 1000
        energy.values[key] = value
    return energy


async def snapshot(ctx: AppContext) -> Energy:
    assert ctx.ha is not None
    states = await ctx.ha.states()
    return read(ctx.settings.energy_sensors, states, await ctx.ha.now())


def _today_lines(e: Energy) -> list[str]:
    lines = []
    solar, forecast = e.get("solar_today"), e.get("forecast_today")
    if solar is not None:
        extra = strings.ENERGY_FORECAST_SUFFIX.format(value=kwh(forecast)) if forecast else ""
        lines.append(strings.ENERGY_SOLAR_TODAY.format(value=kwh(solar), forecast=extra))
    load, imported = e.get("load_today"), e.get("import_today")
    if load is not None:
        line = strings.ENERGY_LOAD_TODAY.format(value=kwh(load))
        if imported is not None and load > 0:
            share = max(0.0, min(1.0, 1 - imported / load))
            line += strings.ENERGY_SELF_SUFFICIENCY.format(percent=round(share * 100))
        lines.append(line)
    exported = e.get("export_today")
    if imported is not None or exported is not None:
        parts = []
        if imported is not None:
            parts.append(strings.ENERGY_IMPORTED.format(value=kwh(imported)))
        if exported is not None:
            parts.append(strings.ENERGY_EXPORTED.format(value=kwh(exported)))
        joined = " · ".join(parts)
        lines.append(f"🔌 {joined[:1].upper()}{joined[1:]}")
    return lines


def _tomorrow_line(e: Energy) -> str:
    forecast = e.get("forecast_tomorrow")
    if forecast is None:
        return ""
    peak = strings.ENERGY_PEAK.format(time=e.peak_tomorrow) if e.peak_tomorrow else ""
    line = strings.ENERGY_TOMORROW.format(value=kwh(forecast), peak=peak)
    if forecast > GOOD_DAY_KWH:
        line += "\n" + strings.ENERGY_GOOD_DAY
    return line


def render_now(e: Energy) -> str:
    lines = [strings.ENERGY_TITLE]
    if (solar := e.get("solar_power")) is not None:
        lines.append(strings.ENERGY_SOLAR_NOW.format(value=kw(solar)))
    if (load := e.get("load_power")) is not None:
        lines.append(strings.ENERGY_LOAD_NOW.format(value=kw(load)))
    soc, battery = e.get("battery_soc"), e.get("battery_power")
    if soc is not None or battery is not None:
        parts = [f"{round(soc)}%"] if soc is not None else []
        if battery is not None and abs(battery) >= 0.01:
            template = strings.ENERGY_CHARGING if battery > 0 else strings.ENERGY_DISCHARGING
            parts.append(template.format(value=kw(abs(battery))))
        lines.append(strings.ENERGY_BATTERY.format(value=" · ".join(parts)))
    if (grid := e.get("grid_power")) is not None:
        template = strings.ENERGY_GRID_EXPORT if grid < 0 else strings.ENERGY_GRID_IMPORT
        lines.append(template.format(value=kw(abs(grid))))
    today = _today_lines(e)
    if today:
        lines += ["", strings.ENERGY_TODAY, *today]
    tomorrow = _tomorrow_line(e)
    if tomorrow:
        lines += ["", tomorrow]
    if len(lines) == 1:
        lines.append(strings.ENERGY_NO_DATA)
    return "\n".join(lines)


def render_report(e: Energy) -> str | None:
    lines = _today_lines(e)
    tomorrow = _tomorrow_line(e)
    if not lines and not tomorrow:
        return None
    out = [strings.ENERGY_REPORT_TITLE, *lines]
    if tomorrow:
        out += ["", tomorrow]
    return "\n".join(out)


async def energia_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        text = render_now(await snapshot(get_ctx(context)))
    except HomeAssistantError:
        text = strings.HA_UNAVAILABLE
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


# --- notifications ---------------------------------------------------------------------


async def on_surplus(app: Application, trigger: dict[str, Any]) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    assert ctx.ha is not None
    today = (await ctx.ha.now()).date().isoformat()
    if await ctx.chat_settings.get(GLOBAL_CHAT, SURPLUS_KEY) == today:
        return  # once a day
    e = await snapshot(ctx)
    grid = e.get("grid_power")
    exported = kw(abs(grid)) if grid is not None and grid < 0 else ""
    text = strings.ENERGY_SURPLUS.format(value=exported or strings.ENERGY_SURPLUS_UNKNOWN)
    if await notify.to_feature(app.bot, ctx, FEATURE_NAME, text):
        await ctx.chat_settings.set(GLOBAL_CHAT, SURPLUS_KEY, today)


async def on_report(app: Application, trigger: dict[str, Any]) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    text = render_report(await snapshot(ctx))
    if text:
        await notify.to_feature(app.bot, ctx, FEATURE_NAME, text)


async def start(app: Application) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    if ctx.events is None or ctx.ha is None:
        return
    events, ha, settings = ctx.events, ctx.ha, ctx.settings

    async def surplus(trigger: dict[str, Any]) -> None:
        await on_surplus(app, trigger)

    async def report(trigger: dict[str, Any]) -> None:
        await on_report(app, trigger)

    async def refresh() -> None:
        grid = settings.energy_grid_power
        if grid:
            # The threshold is in kW; the sensor may report W.
            unit = ((await ha.states()).get(grid) or {}).get("attributes", {})
            factor = 1000 if unit.get("unit_of_measurement") == "W" else 1
            trigger = {
                "trigger": "numeric_state",
                "entity_id": grid,
                "below": -settings.energy_surplus_kw * factor,
                "for": "00:10:00",
            }
            await events.subscribe("energia.surplus", trigger, surplus)
        if settings.energy_report_time:
            await events.subscribe(
                "energia.report", time_trigger(settings.energy_report_time), report
            )

    events.on_connect(refresh)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("energia", energia_command))


def _configured(settings: Settings) -> bool:
    return bool(settings.energy_sensors)


FEATURE = Feature(
    name=FEATURE_NAME,
    description="Fotovoltaico, batteria e consumi",
    register=register,
    commands=[("energia", "fotovoltaico, batteria e consumi di adesso e di oggi")],
    bindable=True,
    topic_hint=strings.ENERGY_TOPIC_HINT,
    requires_homeassistant=True,
    available=_configured,
    start=start,
)
