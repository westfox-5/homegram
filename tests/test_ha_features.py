import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from homegram.db import ChatSettingsRepo, Database, TopicBindingRepo
from homegram.features import energia, pulizie, scene, spazzatura
from homegram.integrations.ha_events import HomeAssistantEvents, time_trigger, websocket_url

# --- WebSocket client ------------------------------------------------------------------


class FakeSocket:
    """Plays the Home Assistant side of the WebSocket protocol."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.inbox.put_nowait(json.dumps({"type": "auth_required"}))

    async def send(self, message: str) -> None:
        data = json.loads(message)
        self.sent.append(data)
        if data["type"] == "auth":
            ok = data["access_token"] == "token"
            await self.inbox.put(json.dumps({"type": "auth_ok" if ok else "auth_invalid"}))
        elif data["type"] == "subscribe_trigger":
            await self.inbox.put(json.dumps({"id": data["id"], "type": "result", "success": True}))

    async def recv(self) -> str:
        return await self.inbox.get()

    async def close(self) -> None:
        self.closed = True

    def fire(self, message_id: int, trigger: dict[str, Any]) -> None:
        event = {"id": message_id, "type": "event", "event": {"variables": {"trigger": trigger}}}
        self.inbox.put_nowait(json.dumps(event))


def test_urls_and_time_trigger() -> None:
    assert websocket_url("https://ha.example/") == "wss://ha.example/api/websocket"
    assert websocket_url("http://10.0.0.2:8123") == "ws://10.0.0.2:8123/api/websocket"
    assert time_trigger("19:30") == {"trigger": "time", "at": "19:30:00"}


async def test_events_subscribe_dispatch_and_replace() -> None:
    socket = FakeSocket()

    async def connector(url: str) -> FakeSocket:
        assert url == "ws://ha.test/api/websocket"
        return socket

    events = HomeAssistantEvents("http://ha.test", "token", connector=connector)
    received: list[dict[str, Any]] = []
    hooks: list[int] = []

    async def callback(trigger: dict[str, Any]) -> None:
        received.append(trigger)

    async def hook() -> None:
        hooks.append(1)
        await events.subscribe("late", {"trigger": "time", "at": "21:00:00"}, callback)

    events.on_connect(hook)
    await events.subscribe("state", {"trigger": "state", "entity_id": "sensor.a"}, callback)
    task = asyncio.create_task(events.run())
    await asyncio.wait_for(events.connected.wait(), 1)

    subscribes = [m for m in socket.sent if m["type"] == "subscribe_trigger"]
    assert hooks == [1] and len(subscribes) == 2  # each trigger sent once
    state_id = next(m["id"] for m in subscribes if m["trigger"]["trigger"] == "state")
    socket.fire(state_id, {"entity_id": "sensor.a"})
    await asyncio.sleep(0.05)
    assert received == [{"entity_id": "sensor.a"}]

    await events.subscribe("state", [], callback)  # removing unsubscribes on the server
    assert socket.sent[-1] == {
        "id": socket.sent[-1]["id"],
        "type": "unsubscribe_events",
        "subscription": state_id,
    }
    socket.fire(state_id, {"entity_id": "sensor.a"})
    await asyncio.sleep(0.05)
    assert len(received) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- energy ------------------------------------------------------------------------------

NOW = datetime(2026, 11, 11, 18, 0, tzinfo=timezone(timedelta(hours=1)))


def st(value: str, unit: str = "") -> dict[str, Any]:
    return {"state": value, "attributes": {"unit_of_measurement": unit} if unit else {}}


def test_energy_render() -> None:
    sensors = {
        "solar_power": "s.solar",
        "grid_power": "s.grid",
        "battery_power": "s.batt",
        "battery_soc": "s.soc",
        "load_today": "s.load",
        "import_today": "s.imp",
        "forecast_tomorrow": "s.fc",
        "peak_tomorrow": "s.peak",
    }
    states = {
        "s.solar": st("1530", "W"),
        "s.grid": st("-1.2", "kW"),
        "s.batt": st("-0.5", "kW"),
        "s.soc": st("80.4", "%"),
        "s.load": st("10", "kWh"),
        "s.imp": st("2.5", "kWh"),
        "s.fc": st("9.5", "kWh"),
        "s.peak": st("2026-11-12T11:00:00+00:00"),
    }
    e = energia.read(sensors, states, NOW)
    text = energia.render_now(e)
    assert "☀️ Fotovoltaico: 1,53 kW" in text
    assert "🔋 Batteria: 80% · in uso 0,50 kW" in text
    assert "🔌 Rete: immissione 1,20 kW" in text
    assert "🏠 Consumati 10,0 kWh · autosufficienza 75%" in text
    assert "🔌 Prelevati 2,5 kWh" in text
    assert "previsti 9,5 kWh, picco alle 12:00." in text  # HA's time zone
    assert "lavatrice" in text  # good day tomorrow
    assert energia.render_report(energia.Energy()) is None


# --- waste -------------------------------------------------------------------------------


WASTE_STATES = {
    "sensor.vpl": {"attributes": {"2026-11-12": "Vpl", "2026-11-19": "Vpl", "friendly_name": "x"}},
    "sensor.umido": {"attributes": {"2026-11-12": "Umido"}},
    "sensor.carta": {"attributes": {"2026-12-30": "Carta"}},
}


def test_waste_schedule_and_texts() -> None:
    schedule = spazzatura.pickups(WASTE_STATES, ["sensor.vpl", "sensor.umido", "sensor.carta"])
    today = date(2026, 11, 11)
    tomorrow = schedule[date(2026, 11, 12)]
    assert [w.label for w in tomorrow] == ["🔵 Plastica", "🟤 Umido"]
    text = spazzatura.render_upcoming(today, schedule)
    assert "<b>Gio 12/11 (domani)</b>: 🔵 Plastica, 🟤 Umido" in text
    assert "30/12" not in text  # beyond 14 days
    assert spazzatura.reminder_text(tomorrow) == (
        "🗑 <b>Domani: 🔵 PLASTICA + 🟤 UMIDO</b>\nStasera metti fuori la plastica e l'umido."
    )


@pytest.fixture
async def app_ctx(db: Database) -> SimpleNamespace:
    bindings = TopicBindingRepo(db)
    await bindings.bind(-100, 5, "spazzatura", None)
    ha = MagicMock()
    ha.now = AsyncMock(return_value=datetime(2026, 11, 11, 19, 30, tzinfo=UTC1))
    ha.states = AsyncMock(return_value=WASTE_STATES)
    ha.render_template = AsyncMock(return_value='["sensor.vpl", "sensor.umido"]')
    ctx = SimpleNamespace(
        ha=ha,
        bindings=bindings,
        chat_settings=ChatSettingsRepo(db),
        settings=SimpleNamespace(ha_waste_sensors=()),
    )
    bot = MagicMock()
    counter = iter(range(100, 200))

    async def send_message(chat_id: int, text: str, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(chat_id=chat_id, message_id=next(counter), text=text, kw=kwargs)

    bot.send_message = AsyncMock(side_effect=send_message)
    bot.edit_message_text = AsyncMock()
    return SimpleNamespace(ctx=ctx, app=SimpleNamespace(bot=bot, bot_data={"homegram": ctx}))


UTC1 = timezone(timedelta(hours=1))


async def test_waste_reminder_flow(app_ctx: SimpleNamespace) -> None:
    app, bot = app_ctx.app, app_ctx.app.bot
    await spazzatura.send_reminder(app, again=False)
    assert bot.send_message.await_count == 1
    call = bot.send_message.call_args
    assert call.args[0] == -100 and call.kwargs["message_thread_id"] == 5
    assert "PLASTICA" in call.args[1]

    await spazzatura.send_reminder(app, again=False)  # same evening: not twice
    await spazzatura.send_reminder(app, again=True)  # nobody answered: repeated
    assert bot.send_message.await_count == 2
    assert bot.send_message.call_args.args[1].startswith("⏰")

    query = MagicMock()
    query.data = "spz:done:2026-11-12"
    query.from_user = SimpleNamespace(first_name="Ilenia")
    query.answer = AsyncMock()
    context = MagicMock()
    context.application.bot_data = {"homegram": app_ctx.ctx}
    context.bot = bot
    await spazzatura.on_callback(SimpleNamespace(callback_query=query), context)
    edited = [c.kwargs["message_id"] for c in bot.edit_message_text.call_args_list]
    assert edited == [100, 101]  # both reminders updated
    assert bot.edit_message_text.call_args.args[0].endswith("✅ Fatto da Ilenia")

    await spazzatura.send_reminder(app, again=True)  # done: no more reminders
    assert bot.send_message.await_count == 2


# --- vacuum & scenes ----------------------------------------------------------------------


def test_vacuum_part_name() -> None:
    assert pulizie.part_name("DEEBOT X11 Durata filtro", "DEEBOT X11") == "Durata filtro"
    assert pulizie.part_name("Filtro", "") == "Filtro"


async def test_vacuum_started_once_until_docked(app_ctx: SimpleNamespace) -> None:
    await app_ctx.ctx.bindings.bind(-100, 9, "pulizie", None)
    app_ctx.ctx.ha.states = AsyncMock(return_value={"sensor.batt": st("80", "%")})
    watcher = pulizie.Watcher(app_ctx.app, pulizie.Robot("vacuum.r", battery="sensor.batt"))
    await watcher.on_started({})
    await watcher.on_started({})  # back from washing the mop
    assert app_ctx.app.bot.send_message.await_count == 1
    assert "batteria 80%" in app_ctx.app.bot.send_message.call_args.args[1]
    await watcher.on_docked({})
    await watcher.on_started({})
    assert app_ctx.app.bot.send_message.await_count == 2


def test_scene_buttons() -> None:
    scenes = [
        scene.Scene("script.sera", "Sera", "mdi:weather-sunset-down"),
        scene.Scene("scene.x", "Una scena dal nome molto molto lungo"),
    ]
    _, markup = scene.render(scenes)
    assert markup is not None
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert labels == ["🌆 Sera", "▶️ Una scena dal nome molt…"]
    assert markup.inline_keyboard[0][0].callback_data == "scn:run:script.sera"
    assert scene.render([]) == (scene.strings.SCENE_EMPTY, None)
