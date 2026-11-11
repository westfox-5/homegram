"""Home Assistant events over the WebSocket API.

Features register *triggers* (the same format as in HA automations: state, numeric_state,
time, ...) with `subscribe`. Home Assistant evaluates them, including `for:` durations and
times of day, and sends the trigger variables back; the bot decides what to post.

The connection is kept open by `run` (a background task) and re-established with a backoff;
every subscription is sent again after a reconnect. Triggers that fire while the bot is
disconnected are lost.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from websockets.asyncio.client import connect

log = logging.getLogger(__name__)

Callback = Callable[[dict[str, Any]], Awaitable[None]]
Trigger = dict[str, Any] | list[dict[str, Any]]

BACKOFF_MIN = 2.0
BACKOFF_MAX = 60.0


class Socket(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[Socket]]


class AuthError(Exception):
    pass


@dataclass
class _Subscription:
    trigger: Trigger
    callback: Callback
    message_id: int | None = None  # id of the subscribe_trigger call on the current socket


def time_trigger(at: str) -> dict[str, Any]:
    """A trigger firing every day at `at` ('21:00' or '21:00:00'), in HA's time zone."""
    return {"trigger": "time", "at": at if at.count(":") == 2 else f"{at}:00"}


def websocket_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url.removeprefix("https://")
    elif url.startswith("http://"):
        url = "ws://" + url.removeprefix("http://")
    return url + "/api/websocket"


async def _default_connect(url: str) -> Socket:
    return await connect(url, max_size=None, ping_interval=30, ping_timeout=30)


class HomeAssistantEvents:
    def __init__(self, base_url: str, token: str, *, connector: Connector | None = None) -> None:
        self._url = websocket_url(base_url)
        self._token = token
        self._connect = connector or _default_connect
        self._subs: dict[str, _Subscription] = {}
        self._on_connect: list[Callable[[], Awaitable[None]]] = []
        self._ids = itertools.count(1)
        self._socket: Socket | None = None
        self._send_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self.connected = asyncio.Event()

    # --- public API -------------------------------------------------------------------

    async def subscribe(self, name: str, trigger: Trigger, callback: Callback) -> None:
        """Add or replace the subscription `name`. An empty trigger list removes it."""
        old = self._subs.pop(name, None)
        if old is not None and old.message_id is not None:
            await self._send_quietly({"type": "unsubscribe_events", "subscription": old.message_id})
        if not trigger:
            return
        sub = _Subscription(trigger, callback)
        self._subs[name] = sub
        if self._socket is not None:
            await self._send_subscribe(sub)

    def on_connect(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Run `hook` after every (re)connection, before the triggers are sent.

        Useful to rebuild triggers that depend on Home Assistant data (e.g. entity lists).
        """
        self._on_connect.append(hook)

    async def run(self) -> None:
        """Keep the connection open forever (run it as a background task)."""
        backoff = BACKOFF_MIN
        while True:
            try:
                await self._session()
                backoff = BACKOFF_MIN
            except asyncio.CancelledError:
                raise
            except AuthError:
                log.error("Home Assistant rejected the token on the WebSocket API")
                backoff = BACKOFF_MAX
            except Exception as exc:
                log.warning("Home Assistant WebSocket disconnected: %s", exc or type(exc).__name__)
            finally:
                self._socket = None
                self.connected.clear()
                for sub in self._subs.values():
                    sub.message_id = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)

    async def close(self) -> None:
        if self._socket is not None:
            with contextlib.suppress(Exception):
                await self._socket.close()

    # --- internals --------------------------------------------------------------------

    async def _session(self) -> None:
        socket = await self._connect(self._url)
        try:
            await self._authenticate(socket)
            self._socket = socket
            for hook in self._on_connect:
                try:
                    await hook()
                except Exception:
                    log.warning("Home Assistant on-connect hook failed", exc_info=True)
            for sub in list(self._subs.values()):
                if sub.message_id is None:  # hooks may have subscribed already
                    await self._send_subscribe(sub)
            self.connected.set()
            log.info("Connected to the Home Assistant WebSocket API (%d triggers)", len(self._subs))
            while True:
                self._handle(json.loads(await socket.recv()))
        finally:
            with contextlib.suppress(Exception):
                await socket.close()

    async def _authenticate(self, socket: Socket) -> None:
        hello = json.loads(await socket.recv())
        if hello.get("type") != "auth_required":
            raise ConnectionError(f"Unexpected greeting: {hello.get('type')}")
        await socket.send(json.dumps({"type": "auth", "access_token": self._token}))
        reply = json.loads(await socket.recv())
        if reply.get("type") != "auth_ok":
            raise AuthError(reply.get("message") or reply.get("type"))

    async def _send(self, message: dict[str, Any]) -> int:
        if self._socket is None:
            raise ConnectionError("not connected")
        async with self._send_lock:
            message_id = next(self._ids)
            await self._socket.send(json.dumps({"id": message_id, **message}))
        return message_id

    async def _send_quietly(self, message: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            await self._send(message)

    async def _send_subscribe(self, sub: _Subscription) -> None:
        sub.message_id = await self._send({"type": "subscribe_trigger", "trigger": sub.trigger})

    def _handle(self, message: dict[str, Any]) -> None:
        if message.get("type") == "result" and not message.get("success", True):
            log.error("Home Assistant refused a trigger: %s", message.get("error"))
            return
        if message.get("type") != "event":
            return
        sub = next((s for s in self._subs.values() if s.message_id == message.get("id")), None)
        if sub is None:
            return
        variables = (message.get("event") or {}).get("variables") or {}
        task = asyncio.create_task(self._dispatch(sub.callback, variables.get("trigger") or {}))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _dispatch(callback: Callback, trigger: dict[str, Any]) -> None:
        try:
            await callback(trigger)
        except Exception:
            log.exception("Error while handling a Home Assistant trigger")
