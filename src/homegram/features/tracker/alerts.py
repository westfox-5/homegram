"""Which tracker sensor changes deserve a Telegram notification, and its text.

Home Assistant sends every state change of the tracked sensors (a `state` trigger); the
sensor name ``<product> · <shop> · prezzo|disponibilità`` tells what changed.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from homegram import strings
from homegram.features.tracker.service import SEPARATOR
from homegram.features.tracker.shops import KIND_PRICE, in_stock

# Smallest price change (EUR) worth a notification.
PRICE_THRESHOLD = 5.0

_BAD_STATES = ("unknown", "unavailable", "none", "")


@dataclass(frozen=True)
class Alert:
    product: str
    shop: str
    entity_id: str
    text: str  # HTML


def _number(state: str) -> float | None:
    try:
        return float(state)
    except ValueError:
        return None


def euro(value: float) -> str:
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def alert_for(trigger: dict[str, Any], muted: set[str], url: str | None = None) -> Alert | None:
    """The notification for a state change, or None if it is not worth one."""
    old, new = trigger.get("from_state"), trigger.get("to_state")
    if not old or not new:
        return None
    parts = str((new.get("attributes") or {}).get("friendly_name") or "").split(SEPARATOR)
    if len(parts) != 3:
        return None
    product, shop, kind = parts
    if product in muted:
        return None
    before, after = str(old.get("state") or ""), str(new.get("state") or "")
    if before.lower() in _BAD_STATES or after.lower() in _BAD_STATES or before == after:
        return None

    shop_html = html.escape(shop)
    if url:
        shop_html = f'<a href="{html.escape(url, quote=True)}">{shop_html}</a>'
    title = html.escape(product)

    if kind == KIND_PRICE:
        f, t = _number(before), _number(after)
        if f is None or t is None:
            return None
        delta = round(t - f, 2)
        if abs(delta) < PRICE_THRESHOLD:
            return None
        text = strings.TRACKER_ALERT_PRICE.format(
            dot="🔴" if delta > 0 else "🟢",
            product=title,
            shop=shop_html,
            old=euro(f),
            new=euro(t),
            arrow="▲" if delta > 0 else "▼",
            delta=euro(abs(delta)),
        )
    else:
        was, now = in_stock(before), in_stock(after)
        if was is None or now is None or was == now:
            return None
        if now:
            unit = (new.get("attributes") or {}).get("unit_of_measurement") or ""
            stock = html.escape(f"{after.strip()} {unit}".strip())
            text = strings.TRACKER_ALERT_BACK.format(product=title, shop=shop_html, stock=stock)
        else:
            text = strings.TRACKER_ALERT_OUT.format(product=title, shop=shop_html)
    return Alert(product, shop, str(new.get("entity_id") or ""), text)
