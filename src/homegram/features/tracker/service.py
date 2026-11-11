"""Price tracker backed by Home Assistant's scrape integration.

Home Assistant is the single source of truth: every tracked link is a scrape config entry
(its title is the product URL) with two sensors named ``<product> · <shop> · <kind>``.
The bot reads them back with a template, so the HA dashboard and automations can use the
same naming convention without any extra state.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from homegram.features.tracker.shops import (
    KIND_PRICE,
    KIND_STOCK,
    Shop,
    expand,
    in_stock,
    resolve,
)
from homegram.integrations.homeassistant import HomeAssistantClient, HomeAssistantError

log = logging.getLogger(__name__)

SCRAPE = "scrape"
SEPARATOR = " · "
MAX_NAME_LENGTH = 60

# All scrape sensors following the naming convention, with their config entry and URL.
TRACKER_TEMPLATE = """
{%- set ns = namespace(out=[]) -%}
{%- for e in integration_entities('scrape') -%}
{%- set parts = (state_attr(e, 'friendly_name') or '').split(' · ') -%}
{%- if parts | length == 3 -%}
{%- set cid = config_entry_id(e) -%}
{%- set ns.out = ns.out + [{
  'entity_id': e, 'product': parts[0], 'shop': parts[1], 'kind': parts[2],
  'state': states(e), 'unit': state_attr(e, 'unit_of_measurement'),
  'entry_id': cid, 'url': config_entry_attr(cid, 'title') if cid else none,
}] -%}
{%- endif -%}
{%- endfor -%}
{{ ns.out | tojson }}
"""


class TrackerError(Exception):
    """A user-facing problem (invalid input, duplicate, HA refused the request)."""

    def __init__(self, code: str, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.details = details


@dataclass
class TrackedLink:
    entry_id: str
    url: str
    product: str
    shop: str
    entities: dict[str, str] = field(default_factory=dict)  # kind -> entity_id
    price: float | None = None
    stock: str | None = None
    stock_unit: str | None = None

    @property
    def available(self) -> bool | None:
        return in_stock(self.stock)


@dataclass
class Product:
    name: str
    links: list[TrackedLink]

    @property
    def best(self) -> TrackedLink | None:
        """Cheapest link that is in stock."""
        candidates = [link for link in self.links if link.price and link.available]
        return min(candidates, key=lambda link: link.price or 0) if candidates else None


def sensor_name(product: str, shop: Shop, kind: str) -> str:
    return SEPARATOR.join((product, shop.name, kind))


def clean_product_name(name: str) -> str:
    cleaned = " ".join(name.replace("·", " ").split())
    if not cleaned:
        raise TrackerError("empty_name")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise TrackerError("long_name", max=MAX_NAME_LENGTH)
    return cleaned


def _to_float(state: str | None) -> float | None:
    try:
        value = float(state)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def group_products(rows: list[dict[str, Any]]) -> list[Product]:
    """Turn the template rows (one per sensor) into products with their links."""
    links: dict[str, TrackedLink] = {}
    for row in rows:
        entry_id, url = row.get("entry_id"), row.get("url")
        if not entry_id or not url:
            continue
        link = links.setdefault(
            entry_id, TrackedLink(entry_id, url, str(row["product"]), str(row["shop"]))
        )
        kind = row.get("kind")
        link.entities[kind] = row["entity_id"]
        if kind == KIND_PRICE:
            link.price = _to_float(row.get("state"))
        elif kind == KIND_STOCK:
            link.stock = row.get("state")
            link.stock_unit = row.get("unit")

    products: dict[str, Product] = {}
    for link in links.values():
        key = link.product.casefold()
        products.setdefault(key, Product(link.product, [])).links.append(link)
    for product in products.values():
        product.links.sort(key=lambda link: link.shop.casefold())
    return sorted(products.values(), key=lambda p: p.name.casefold())


class TrackerService:
    def __init__(self, ha: HomeAssistantClient) -> None:
        self._ha = ha
        # Called after products or links change (e.g. to update the notification triggers).
        self._listeners: list[Callable[[], Awaitable[None]]] = []

    def on_change(self, listener: Callable[[], Awaitable[None]]) -> None:
        self._listeners.append(listener)

    async def _changed(self) -> None:
        for listener in self._listeners:
            try:
                await listener()
            except Exception:
                log.warning("Tracker change listener failed", exc_info=True)

    async def entities(self) -> list[str]:
        """Every tracked sensor (price and availability of every link)."""
        return sorted(
            entity
            for product in await self.products()
            for link in product.links
            for entity in link.entities.values()
        )

    async def products(self) -> list[Product]:
        raw = await self._ha.render_template(TRACKER_TEMPLATE)
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HomeAssistantError(f"Unexpected tracker template output: {raw[:200]!r}") from exc
        return group_products(rows)

    async def find_product(self, name: str) -> Product | None:
        key = name.casefold()
        return next((p for p in await self.products() if p.name.casefold() == key), None)

    async def product_of(self, entry_id: str) -> Product | None:
        """The product a link (config entry) belongs to."""
        for product in await self.products():
            if any(link.entry_id == entry_id for link in product.links):
                return product
        return None

    async def check_url(self, url: str) -> tuple[Shop, str]:
        """Expand and resolve `url` before asking anything else about it.

        Raises `UnsupportedUrl` (or `ShortLinkError`) and `TrackerError("duplicate_url")`.
        """
        shop, canonical = resolve(await expand(url))
        for product in await self.products():
            if any(link.url == canonical for link in product.links):
                raise TrackerError("duplicate_url", product=product.name)
        return shop, canonical

    async def add(self, product_name: str, url: str) -> tuple[Product, TrackedLink, bool]:
        """Track `url` under `product_name` (created if new).

        Returns the updated product, the new link and whether the product is new.
        """
        name = clean_product_name(product_name)
        shop, canonical = resolve(await expand(url))

        products = await self.products()
        for product in products:
            for link in product.links:
                if link.url == canonical:
                    raise TrackerError("duplicate_url", product=product.name)
        existing = next((p for p in products if p.name.casefold() == name.casefold()), None)
        if existing is not None:
            name = existing.name  # keep the original spelling
            if any(link.shop == shop.name for link in existing.links):
                raise TrackerError("duplicate_shop", product=name, shop=shop.name)

        result = await self._ha.config_flow(SCRAPE, shop.resource_data(canonical))
        if result.get("type") != "create_entry":
            log.warning("Scrape config flow did not create an entry: %s", result)
            raise TrackerError("flow_failed", errors=result.get("errors") or result.get("reason"))
        entry_id = result["result"]["entry_id"]

        try:
            for spec in shop.sensors:
                sub = await self._ha.subentry_flow(
                    entry_id, "entity", spec.subentry_data(sensor_name(name, shop, spec.kind))
                )
                if sub.get("type") != "create_entry":
                    log.warning("Scrape sensor flow failed: %s", sub)
                    raise TrackerError("flow_failed", errors=sub.get("errors") or sub.get("reason"))
        except Exception:
            # Do not leave a half-configured resource behind.
            await self._safe_delete(entry_id)
            raise

        link = await self._wait_for_link(entry_id, len(shop.sensors))
        if link is None:  # sensors not loaded yet: report what we know
            link = TrackedLink(entry_id, canonical, name, shop.name)
        await self._changed()
        product = await self.find_product(name) or Product(name, [link])
        return product, link, existing is None

    async def remove_link(self, entry_id: str) -> TrackedLink | None:
        for product in await self.products():
            for link in product.links:
                if link.entry_id == entry_id:
                    await self._ha.delete_config_entry(entry_id)
                    await self._changed()
                    return link
        return None

    async def remove_product(self, entry_id: str) -> Product | None:
        """Remove every link of the product that `entry_id` belongs to."""
        for product in await self.products():
            if any(link.entry_id == entry_id for link in product.links):
                for link in product.links:
                    await self._ha.delete_config_entry(link.entry_id)
                await self._changed()
                return product
        return None

    async def _wait_for_link(
        self, entry_id: str, sensors: int, *, wait: float = 20.0, interval: float = 2.0
    ) -> TrackedLink | None:
        """Wait until the new sensors exist and have a first value."""
        link: TrackedLink | None = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait
        while True:
            for product in await self.products():
                for candidate in product.links:
                    if candidate.entry_id == entry_id:
                        link = candidate
            ready = link is not None and len(link.entities) >= sensors and link.price is not None
            if ready or loop.time() >= deadline:
                return link
            await asyncio.sleep(interval)

    async def _safe_delete(self, entry_id: str) -> None:
        try:
            await self._ha.delete_config_entry(entry_id)
        except HomeAssistantError:
            log.warning("Could not roll back scrape entry %s", entry_id, exc_info=True)
