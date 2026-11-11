"""Robot vacuum notifications, posted to the topics bound with ``/bind pulizie``.

- started: it leaves the dock to clean (not again when it only goes back to wash the mop:
  the next start is announced after it has been docked for 10 minutes);
- error: stuck or in error for a minute;
- parts: a lifespan sensor (brushes, filter, bag, mop, detergent…) drops below the threshold.

HA_VACUUM is required; the battery, error and part sensors are found on the robot's device
when not configured.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from telegram.ext import Application

from homegram import notify, strings
from homegram.config import Settings
from homegram.context import CTX_KEY, AppContext
from homegram.features.base import Feature
from homegram.integrations.homeassistant import HomeAssistantClient

log = logging.getLogger(__name__)

FEATURE_NAME = "pulizie"
NO_ERROR = ("", "0", "noerror")

# Sensors of the robot's device, for the ones not configured explicitly.
DEVICE_TEMPLATE = """
{%- set ns = namespace(battery='', error='', parts=[]) -%}
{%- for e in device_entities(device_id(VACUUM)) if e.startswith('sensor.') -%}
{%- if state_attr(e, 'device_class') == 'battery' -%}{%- set ns.battery = e -%}
{%- elif e.endswith('_errore') or e.endswith('_error') -%}{%- set ns.error = e -%}
{%- elif state_attr(e, 'unit_of_measurement') == '%' -%}{%- set ns.parts = ns.parts + [e] -%}
{%- endif -%}
{%- endfor -%}
{{ {'battery': ns.battery, 'error': ns.error, 'parts': ns.parts} | tojson }}
"""


@dataclass
class Robot:
    vacuum: str
    battery: str = ""
    error: str = ""
    parts: list[str] = field(default_factory=list)


async def discover(ha: HomeAssistantClient, settings: Settings) -> Robot:
    assert settings.ha_vacuum
    robot = Robot(
        settings.ha_vacuum,
        settings.ha_vacuum_battery or "",
        settings.ha_vacuum_error or "",
        list(settings.ha_vacuum_parts),
    )
    if robot.battery and robot.error and robot.parts:
        return robot
    found = json.loads(
        await ha.render_template(DEVICE_TEMPLATE.replace("VACUUM", json.dumps(robot.vacuum)))
    )
    robot.battery = robot.battery or found["battery"]
    robot.error = robot.error or found["error"]
    robot.parts = robot.parts or found["parts"]
    return robot


def part_name(friendly_name: str, device_name: str) -> str:
    """'DEEBOT X11 Durata filtro' -> 'Durata filtro'."""
    name = friendly_name
    if device_name and name.lower().startswith(device_name.lower()):
        name = name[len(device_name) :].strip()
    return name[:1].upper() + name[1:] if name else friendly_name


class Watcher:
    """State kept between triggers (in memory: a restart may repeat one 'started')."""

    def __init__(self, app: Application, robot: Robot) -> None:
        self.app = app
        self.robot = robot
        self.announced = False

    @property
    def ctx(self) -> AppContext:
        return self.app.bot_data[CTX_KEY]

    async def _state(self, entity_id: str) -> dict[str, Any]:
        if not entity_id or self.ctx.ha is None:
            return {}
        return (await self.ctx.ha.states()).get(entity_id) or {}

    async def _send(self, text: str) -> None:
        await notify.to_feature(self.app.bot, self.ctx, FEATURE_NAME, text)

    async def on_started(self, trigger: dict[str, Any]) -> None:
        if self.announced:
            return  # back from washing the mop
        self.announced = True
        battery = str((await self._state(self.robot.battery)).get("state", ""))
        suffix = strings.VACUUM_BATTERY.format(value=battery) if battery.isdigit() else ""
        await self._send(strings.VACUUM_STARTED.format(battery=suffix))

    async def on_docked(self, trigger: dict[str, Any]) -> None:
        self.announced = False

    async def on_error(self, trigger: dict[str, Any]) -> None:
        state = await self._state(self.robot.error)
        description = str((state.get("attributes") or {}).get("description") or "")
        detail = ""
        if description and description.split(":")[0].strip().lower() not in NO_ERROR:
            detail = strings.VACUUM_ERROR_DETAIL.format(detail=html.escape(description))
        await self._send(strings.VACUUM_ERROR.format(detail=detail))

    async def on_part(self, trigger: dict[str, Any]) -> None:
        new = trigger.get("to_state") or {}
        try:
            value = round(float(new.get("state")))
        except (TypeError, ValueError):
            return
        device = str(
            ((await self._state(self.robot.vacuum)).get("attributes") or {}).get("friendly_name")
            or ""
        )
        name = part_name(str((new.get("attributes") or {}).get("friendly_name") or ""), device)
        await self._send(strings.VACUUM_PART.format(part=html.escape(name), value=value))


async def start(app: Application) -> None:
    ctx: AppContext = app.bot_data[CTX_KEY]
    if ctx.events is None or ctx.ha is None or not ctx.settings.ha_vacuum:
        return
    events, ha, settings = ctx.events, ctx.ha, ctx.settings
    watcher = Watcher(app, Robot(settings.ha_vacuum))

    async def refresh() -> None:
        watcher.robot = await discover(ha, settings)
        vacuum = watcher.robot.vacuum
        await events.subscribe(
            "pulizie.started",
            {"trigger": "state", "entity_id": vacuum, "from": ["docked", "idle"], "to": "cleaning"},
            watcher.on_started,
        )
        await events.subscribe(
            "pulizie.docked",
            {"trigger": "state", "entity_id": vacuum, "to": "docked", "for": "00:10:00"},
            watcher.on_docked,
        )
        await events.subscribe(
            "pulizie.error",
            {"trigger": "state", "entity_id": vacuum, "to": "error", "for": "00:01:00"},
            watcher.on_error,
        )
        parts = watcher.robot.parts
        part_trigger = (
            {
                "trigger": "numeric_state",
                "entity_id": parts,
                "below": settings.vacuum_parts_threshold,
            }
            if parts
            else []
        )
        await events.subscribe("pulizie.parts", part_trigger, watcher.on_part)

    events.on_connect(refresh)


def _configured(settings: Settings) -> bool:
    return bool(settings.ha_vacuum)


FEATURE = Feature(
    name=FEATURE_NAME,
    description="Notifiche del robot aspirapolvere",
    register=lambda app: None,
    bindable=True,
    topic_hint=strings.VACUUM_TOPIC_HINT,
    requires_homeassistant=True,
    available=_configured,
    start=start,
)
