import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from homegram.features.tracker.alerts import alert_for
from homegram.features.tracker.handlers import (
    format_price,
    render_notifications,
    render_products,
    split_args,
)
from homegram.features.tracker.service import (
    TrackerError,
    TrackerService,
    clean_product_name,
    group_products,
)
from homegram.features.tracker.shops import (
    WISP,
    ShortLinkError,
    UnsupportedUrl,
    expand,
    in_stock,
    resolve,
)
from homegram.integrations.homeassistant import HomeAssistantClient, HomeAssistantError

BASE = "http://ha.test:8123"
WISP_URL = "https://wisp.store/unifi/10765-ubiquiti-unifi-u7-pro-wall-u7-pro-wall.html"
AMAZON_URL = "https://www.amazon.it/dp/B0D9JTNXNL"
FLOW = f"{BASE}/api/config/config_entries/flow"
SUBFLOW = f"{BASE}/api/config/config_entries/subentries/flow"


def row(
    entity: str, product: str, shop: str, kind: str, state: str, entry: str, url: str, unit=None
):  # type: ignore[no-untyped-def]
    return {
        "entity_id": entity,
        "product": product,
        "shop": shop,
        "kind": kind,
        "state": state,
        "unit": unit,
        "entry_id": entry,
        "url": url,
    }


ROWS = [
    row("sensor.u7_wisp_prezzo", "U7 Pro Wall", "wisp.store", "prezzo", "215.28", "e1", WISP_URL),
    row(
        "sensor.u7_wisp_disp",
        "U7 Pro Wall",
        "wisp.store",
        "disponibilità",
        "20",
        "e1",
        WISP_URL,
        "pz",
    ),
    row("sensor.u7_amz_prezzo", "U7 Pro Wall", "Amazon", "prezzo", "222.0", "e2", AMAZON_URL),
    row(
        "sensor.u7_amz_disp",
        "U7 Pro Wall",
        "Amazon",
        "disponibilità",
        "Disponibilità: solo 4",
        "e2",
        AMAZON_URL,
    ),
]


# --- shops -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "shop", "canonical"),
    [
        (WISP_URL + "?utm_source=x#top", "wisp.store", WISP_URL),
        (
            "https://www.amazon.it/Ubiquiti-UniFi-Flex-2-5G-PoE/dp/B0DV6CDXKT/ref=sr_1_1?th=1",
            "Amazon",
            "https://www.amazon.it/dp/B0DV6CDXKT",
        ),
        (
            "https://amazon.de/gp/product/b0bcpjqgsq",
            "Amazon.de",
            "https://www.amazon.de/dp/B0BCPJQGSQ",
        ),
    ],
)
def test_resolve(url: str, shop: str, canonical: str) -> None:
    found, normalized = resolve(url)
    assert (found.name, normalized) == (shop, canonical)


@pytest.mark.parametrize(
    "url",
    ["not a url", "https://example.com/product", "https://www.amazon.it/", "https://wisp.store/"],
)
def test_resolve_rejects(url: str) -> None:
    with pytest.raises(UnsupportedUrl):
        resolve(url)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("20", True),
        ("0", False),
        ("Disponibilità immediata", True),
        ("Attualmente non disponibile.", False),
        ("unavailable", None),
        (None, None),
    ],
)
def test_in_stock(state: str | None, expected: bool | None) -> None:
    assert in_stock(state) is expected


def test_payloads() -> None:
    resource = WISP.resource_data(WISP_URL)
    assert resource["resource"] == WISP_URL and resource["auth"] == {}
    sensor = WISP.sensors[0].subentry_data("U7 Pro Wall · wisp.store · prezzo")
    assert sensor["select"] == 'meta[property="product:price:amount"]'
    assert sensor["additional"]["attribute"] == "content"
    assert sensor["additional"]["unit_of_measurement"] == "EUR"


# --- grouping & rendering -------------------------------------------------------


def test_group_products_and_best_price() -> None:
    [product] = group_products(ROWS)
    assert product.name == "U7 Pro Wall"
    assert [link.shop for link in product.links] == ["Amazon", "wisp.store"]
    assert product.best is not None and product.best.shop == "wisp.store"


def test_best_skips_out_of_stock() -> None:
    rows = [dict(r) for r in ROWS]
    rows[1]["state"] = "0"
    [product] = group_products(rows)
    assert product.best is not None and product.best.shop == "Amazon"


def test_render_products() -> None:
    text, markup = render_products(group_products(ROWS))
    assert "<b>215,28 €</b>" in text
    assert "222,00 €" in text and "solo 4" in text and "20 pz" in text
    assert f'href="{WISP_URL}"' in text
    assert markup is not None
    data = [b.callback_data for r in markup.inline_keyboard for b in r]
    assert "trk:rm:e1" in data and all(len(d.encode()) <= 64 for d in data)


def test_render_empty() -> None:
    text, markup = render_products([])
    assert markup is None and "/tracker_aggiungi" in text


def test_format_price() -> None:
    assert format_price(1234.5) == "1.234,50 €"
    assert format_price(None) == "—"


@pytest.mark.parametrize(
    ("text", "name", "url"),
    [
        ("/tracker_aggiungi U7 Pro Wall https://x.it/a", "U7 Pro Wall", "https://x.it/a"),
        ("/tracker_aggiungi https://x.it/a U7 Pro Wall", "U7 Pro Wall", "https://x.it/a"),
        ("/tracker_aggiungi U7 Pro Wall", "U7 Pro Wall", None),
        ("/tracker_aggiungi", "", None),
    ],
)
def test_split_args(text: str, name: str, url: str | None) -> None:
    assert split_args(text) == (name, url)


def test_clean_product_name() -> None:
    assert clean_product_name("  U7 ·  Pro  Wall ") == "U7 Pro Wall"
    with pytest.raises(TrackerError):
        clean_product_name("x" * 61)


# --- service against a mocked Home Assistant ----------------------------------------


@pytest.fixture
async def ha() -> AsyncIterator[HomeAssistantClient]:
    client = HomeAssistantClient(BASE, "secret-token")
    yield client
    await client.close()


def mock_template(*outputs: list[dict[str, Any]]) -> respx.Route:
    return respx.post(f"{BASE}/api/template").mock(
        side_effect=[httpx.Response(200, text=json.dumps(o)) for o in outputs]
    )


def mock_flows(entry_id: str = "new") -> tuple[respx.Route, respx.Route]:
    respx.post(FLOW).mock(return_value=httpx.Response(200, json={"flow_id": "f1"}))
    flow = respx.post(f"{FLOW}/f1").mock(
        return_value=httpx.Response(
            200, json={"type": "create_entry", "result": {"entry_id": entry_id}}
        )
    )
    respx.post(SUBFLOW).mock(return_value=httpx.Response(200, json={"flow_id": "s1"}))
    sub = respx.post(f"{SUBFLOW}/s1").mock(
        return_value=httpx.Response(200, json={"type": "create_entry"})
    )
    return flow, sub


@respx.mock
async def test_add_link_to_existing_product(ha: HomeAssistantClient) -> None:
    wisp_only = ROWS[:2]
    created = [
        row("sensor.a", "U7 Pro Wall", "Amazon", "prezzo", "222.0", "new", AMAZON_URL),
        row("sensor.b", "U7 Pro Wall", "Amazon", "disponibilità", "ok", "new", AMAZON_URL),
    ]
    mock_template(wisp_only, wisp_only + created, wisp_only + created)
    flow, sub = mock_flows()

    service = TrackerService(ha)
    product, link, is_new = await service.add(
        "u7 pro wall", "https://www.amazon.it/x/dp/B0D9JTNXNL?th=1"
    )

    assert not is_new
    assert product.name == "U7 Pro Wall" and len(product.links) == 2
    assert link.entry_id == "new" and link.price == 222.0
    assert json.loads(flow.calls.last.request.content)["resource"] == AMAZON_URL
    names = [json.loads(c.request.content)["name"] for c in sub.calls]
    assert names == ["U7 Pro Wall · Amazon · prezzo", "U7 Pro Wall · Amazon · disponibilità"]


@respx.mock
async def test_add_rejects_duplicates(ha: HomeAssistantClient) -> None:
    mock_template(ROWS, ROWS)
    service = TrackerService(ha)
    with pytest.raises(TrackerError) as exc:
        await service.add("Altro", WISP_URL)
    assert exc.value.code == "duplicate_url"
    with pytest.raises(TrackerError) as exc:
        await service.add("U7 Pro Wall", "https://www.amazon.it/dp/B000000000")
    assert exc.value.code == "duplicate_shop"


@respx.mock
async def test_add_rolls_back_on_sensor_failure(ha: HomeAssistantClient) -> None:
    mock_template([])
    mock_flows()
    respx.post(f"{SUBFLOW}/s1").mock(
        return_value=httpx.Response(200, json={"type": "form", "errors": {"base": "x"}})
    )
    delete = respx.delete(f"{BASE}/api/config/config_entries/entry/new").mock(
        return_value=httpx.Response(200, json={"require_restart": False})
    )
    with pytest.raises(TrackerError):
        await TrackerService(ha).add("Switch", WISP_URL)
    assert delete.called


@respx.mock
async def test_forbidden_token(ha: HomeAssistantClient) -> None:
    mock_template([])
    respx.post(FLOW).mock(return_value=httpx.Response(401))
    with pytest.raises(HomeAssistantError) as exc:
        await TrackerService(ha).add("Switch", WISP_URL)
    assert exc.value.forbidden


@respx.mock
async def test_remove_link_notifies_listeners(ha: HomeAssistantClient) -> None:
    mock_template(ROWS, ROWS[:2])
    delete = respx.delete(f"{BASE}/api/config/config_entries/entry/e2").mock(
        return_value=httpx.Response(200, json={})
    )
    service = TrackerService(ha)
    seen: list[list[str]] = []

    async def listener() -> None:
        seen.append(await service.entities())

    service.on_change(listener)
    link = await service.remove_link("e2")

    assert link is not None and link.shop == "Amazon" and delete.called
    assert seen == [["sensor.u7_wisp_disp", "sensor.u7_wisp_prezzo"]]


@respx.mock
async def test_remove_product(ha: HomeAssistantClient) -> None:
    mock_template(ROWS)
    delete = respx.delete(url__regex=rf"{BASE}/api/config/config_entries/entry/e[12]").mock(
        return_value=httpx.Response(200, json={})
    )
    product = await TrackerService(ha).remove_product("e1")
    assert product is not None and delete.call_count == 2


# --- notifications -------------------------------------------------------------------


def state(entity: str, name: str, value: str, unit: str = "") -> dict[str, Any]:
    attributes = {"friendly_name": name}
    if unit:
        attributes["unit_of_measurement"] = unit
    return {"entity_id": entity, "state": value, "attributes": attributes}


def change(name: str, old: str, new: str, unit: str = "") -> dict[str, Any]:
    return {
        "from_state": state("sensor.x", name, old, unit),
        "to_state": state("sensor.x", name, new, unit),
    }


PRICE = "U7 Pro · Amazon · prezzo"
STOCK = "U7 Pro · wisp.store · disponibilità"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("199.99", "199.98", None),
        ("199.99", "195.00", None),
        ("199.99", "194.99", "🟢 <b>U7 Pro</b>\nAmazon: 199,99 € → 194,99 € (▼ 5,00 €)"),
        ("95.10", "100.10", "🔴 <b>U7 Pro</b>\nAmazon: 95,10 € → 100,10 € (▲ 5,00 €)"),
        ("abc", "190", None),
        ("unavailable", "150", None),
    ],
)
def test_price_alerts(old: str, new: str, expected: str | None) -> None:
    alert = alert_for(change(PRICE, old, new), set())
    assert (alert.text if alert else None) == expected


def test_stock_alerts_and_mute() -> None:
    back = alert_for(change(STOCK, "0", "3", "pz"), set(), "https://wisp.store/x")
    assert back is not None
    assert back.text == (
        '✅ <b>U7 Pro</b>\nDi nuovo disponibile su <a href="https://wisp.store/x">wisp.store</a>'
        " (3 pz)"
    )
    out = alert_for(
        change("P · Amazon · disponibilità", "Disponibilità immediata", "Non disponibile"), set()
    )
    assert out is not None and out.text.startswith("❌ <b>P</b>")
    assert alert_for(change(STOCK, "5", "4", "pz"), set()) is None  # pieces sold: no alert
    assert alert_for(change(STOCK, "0", "3", "pz"), {"U7 Pro"}) is None  # muted
    assert alert_for(change("Not a tracker sensor", "1", "100"), set()) is None


def test_render_notifications() -> None:
    text, markup = render_notifications(["A", "B"], {"B"}, [])
    assert "/bind tracker" in text and "🔔 A" in text and "🔕 B" in text
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert labels[:2] == ["🔔 A", "🔕 B"]
    text, _ = render_notifications([], set(), ["topic 7"])
    assert "Arrivano qui: topic 7" in text


# --- short links ---------------------------------------------------------------------


@respx.mock
async def test_expand_short_link() -> None:
    target = "https://www.amazon.it/dp/B0F7HGLFHS?ref=cm_sw_r_cso_cp_apan_dp_X&social_share=X"
    respx.get("https://amzn.eu/d/00tUfN4F").respond(301, headers={"Location": target})
    url = await expand("https://amzn.eu/d/00tUfN4F")
    assert url == target
    assert resolve(url)[1] == "https://www.amazon.it/dp/B0F7HGLFHS"


@respx.mock
async def test_expand_follows_short_hops() -> None:
    respx.get("https://a.co/d/x").respond(302, headers={"Location": "https://amzn.to/y"})
    respx.get("https://amzn.to/y").respond(
        301, headers={"Location": "https://www.amazon.de/dp/B0DV6CDXKT"}
    )
    assert await expand("https://a.co/d/x") == "https://www.amazon.de/dp/B0DV6CDXKT"


async def test_expand_leaves_other_urls() -> None:
    assert await expand(" https://www.amazon.it/dp/B0DV6CDXKT ") == (
        "https://www.amazon.it/dp/B0DV6CDXKT"
    )


@respx.mock
@pytest.mark.parametrize("response", [httpx.Response(404), httpx.ConnectError("down")])
async def test_expand_failures(response: Any) -> None:
    route = respx.get("https://amzn.eu/d/broken")
    if isinstance(response, Exception):
        route.side_effect = response
    else:
        route.respond(404)
    with pytest.raises(ShortLinkError):
        await expand("https://amzn.eu/d/broken")
