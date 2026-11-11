"""Supported shops: how to normalize a product URL and which HTML elements to scrape.

To support a new shop, add a `Shop` to `SHOPS`. Each shop produces two Home Assistant scrape
sensors per link: the price (a number, EUR) and the availability (a number of pieces or a text).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import httpx

KIND_PRICE = "prezzo"
KIND_STOCK = "disponibilità"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SensorSpec:
    kind: str
    select: str
    value_template: str
    attribute: str | None = None
    availability: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    unit: str | None = None

    def subentry_data(self, name: str) -> dict[str, Any]:
        """Payload of the scrape integration's "add sensor" subentry flow."""
        additional: dict[str, Any] = {"value_template": self.value_template}
        for key, value in (
            ("attribute", self.attribute),
            ("availability", self.availability),
            ("device_class", self.device_class),
            ("state_class", self.state_class),
            ("unit_of_measurement", self.unit),
        ):
            if value:
                additional[key] = value
        return {"name": name, "select": self.select, "index": 0, "additional": additional}


@dataclass(frozen=True)
class Shop:
    name: str  # shown to users and part of the sensor names, e.g. "wisp.store"
    hosts: tuple[str, ...]
    normalize: Callable[[SplitResult], str | None]
    sensors: tuple[SensorSpec, ...]
    headers: dict[str, str] = field(default_factory=dict)

    def resource_data(self, url: str) -> dict[str, Any]:
        """Payload of the scrape integration's "add resource" config flow."""
        additional: dict[str, Any] = {"verify_ssl": True, "timeout": 15, "encoding": "UTF-8"}
        if self.headers:
            additional["headers"] = dict(self.headers)
        return {"resource": url, "method": "GET", "auth": {}, "additional": additional}


# --- wisp.store (PrestaShop): price in an OpenGraph meta tag, stock in a data attribute ----


def _strip_query(url: SplitResult) -> str | None:
    if not url.path or url.path == "/":
        return None
    return urlunsplit(("https", url.hostname, url.path, "", ""))


WISP = Shop(
    name="wisp.store",
    hosts=("wisp.store", "www.wisp.store"),
    normalize=_strip_query,
    sensors=(
        SensorSpec(
            kind=KIND_PRICE,
            select='meta[property="product:price:amount"]',
            attribute="content",
            value_template="{{ value | float(0) }}",
            device_class="monetary",
            unit="EUR",
        ),
        SensorSpec(
            kind=KIND_STOCK,
            select="#product-availability",
            attribute="data-wisp-physical",
            value_template="{{ value | int(0) }}",
            state_class="measurement",
            unit="pz",
        ),
    ),
)

# --- Amazon (EU stores, prices formatted like "1.234,56€") ---------------------------------

_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)


def _amazon(tld: str) -> Callable[[SplitResult], str | None]:
    def normalize(url: SplitResult) -> str | None:
        match = _ASIN.search(url.path + "/")
        if not match:
            return None
        return f"https://www.amazon.{tld}/dp/{match.group(1).upper()}"

    return normalize


_AMAZON_PRICE = SensorSpec(
    kind=KIND_PRICE,
    select="#corePrice_feature_div .a-offscreen",
    value_template=(
        "{{ value | replace('€','') | replace('.','') | replace(',','.') | trim | float(0) }}"
    ),
    availability="{{ value is not none and '€' in value }}",
    device_class="monetary",
    unit="EUR",
)
_AMAZON_STOCK = SensorSpec(
    kind=KIND_STOCK, select="#availability span", value_template="{{ value | trim }}"
)


def _amazon_shop(tld: str, name: str, language: str) -> Shop:
    return Shop(
        name=name,
        hosts=(f"amazon.{tld}", f"www.amazon.{tld}"),
        normalize=_amazon(tld),
        sensors=(_AMAZON_PRICE, _AMAZON_STOCK),
        headers={
            "User-Agent": BROWSER_UA,
            "Accept-Language": f"{language};q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        },
    )


SHOPS: tuple[Shop, ...] = (
    WISP,
    _amazon_shop("it", "Amazon", "it-IT,it"),
    _amazon_shop("de", "Amazon.de", "de-DE,de"),
    _amazon_shop("fr", "Amazon.fr", "fr-FR,fr"),
    _amazon_shop("es", "Amazon.es", "es-ES,es"),
)


class UnsupportedUrl(ValueError):
    pass


class ShortLinkError(UnsupportedUrl):
    """A short link that could not be expanded (network error, no redirect, too many hops)."""


# Share links of the Amazon app ("https://amzn.eu/d/…"): a redirect to the product page.
SHORT_LINK_HOSTS = frozenset({"amzn.eu", "amzn.to", "a.co"})
_MAX_HOPS = 5
_TIMEOUT = 10  # seconds


async def expand(url: str) -> str:
    """Follow the redirects of a short link and return the product URL it points to.

    Other URLs are returned unchanged. Only the redirect headers are read: the target page
    is never downloaded.
    """
    url = url.strip()
    if (urlsplit(url).hostname or "").lower() not in SHORT_LINK_HOSTS:
        return url
    current = url
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": BROWSER_UA}
        ) as client:
            for _ in range(_MAX_HOPS):
                async with client.stream("GET", current) as response:
                    location = response.headers.get("location")
                    if not response.is_redirect or not location:
                        raise ShortLinkError(url)
                current = urljoin(current, location)
                if (urlsplit(current).hostname or "").lower() not in SHORT_LINK_HOSTS:
                    return current
    except httpx.HTTPError as exc:
        raise ShortLinkError(url) from exc
    raise ShortLinkError(url)


def resolve(url: str) -> tuple[Shop, str]:
    """Find the shop of a product URL and return it with the canonical URL to scrape.

    Raises `UnsupportedUrl` if the URL is malformed, from an unknown shop, or not a product page.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsupportedUrl(url)
    host = parts.hostname.lower()
    for shop in SHOPS:
        if host in shop.hosts:
            canonical = shop.normalize(parts)
            if canonical is None:
                raise UnsupportedUrl(url)
            return shop, canonical
    raise UnsupportedUrl(url)


# Lower-case fragments of availability texts that mean "out of stock".
_OUT_OF_STOCK = (
    "non disponibile",
    "esaurito",
    "currently unavailable",
    "out of stock",
    "nicht verfügbar",
    "derzeit nicht",
    "indisponible",
    "no disponible",
)


def in_stock(state: str | None) -> bool | None:
    """Interpret an availability sensor: a piece count or a shop text. None if unknown."""
    if state is None or state in ("unknown", "unavailable", ""):
        return None
    try:
        return float(state) > 0
    except ValueError:
        text = state.lower()
        return not any(fragment in text for fragment in _OUT_OF_STOCK)
