import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from homegram.features.tracker import notifications
from homegram.features.tracker.handlers import (
    format_price,
    render_notifications,
    render_products,
    split_args,
)
from homegram.features.tracker.service import (
    NotificationStatus,
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

    service = TrackerService(ha, automation_id=None)
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
async def test_remove_link_syncs_automation(ha: HomeAssistantClient) -> None:
    mock_template(ROWS, ROWS[:2])
    delete = respx.delete(f"{BASE}/api/config/config_entries/entry/e2").mock(
        return_value=httpx.Response(200, json={})
    )
    config = {"triggers": [{"trigger": "state", "entity_id": ["old"]}], "actions": []}
    respx.get(f"{BASE}/api/config/automation/config/auto").mock(
        return_value=httpx.Response(200, json=config)
    )
    save = respx.post(f"{BASE}/api/config/automation/config/auto").mock(
        return_value=httpx.Response(200, json={"result": "ok"})
    )

    link = await TrackerService(ha, "auto").remove_link("e2")

    assert link is not None and link.shop == "Amazon" and delete.called
    saved = json.loads(save.calls.last.request.content)
    assert saved["triggers"][0]["entity_id"] == ["sensor.u7_wisp_disp", "sensor.u7_wisp_prezzo"]


@respx.mock
async def test_sync_skips_missing_automation(ha: HomeAssistantClient) -> None:
    respx.get(f"{BASE}/api/config/automation/config/auto").mock(
        return_value=httpx.Response(404, json={"message": "Resource not found"})
    )
    assert await TrackerService(ha, "auto").sync_automation() is False


@respx.mock
async def test_remove_product(ha: HomeAssistantClient) -> None:
    mock_template(ROWS)
    delete = respx.delete(url__regex=rf"{BASE}/api/config/config_entries/entry/e[12]").mock(
        return_value=httpx.Response(200, json={})
    )
    product = await TrackerService(ha).remove_product("e1")
    assert product is not None and delete.call_count == 2


# --- notifications -------------------------------------------------------------------


def test_notification_config_roundtrip() -> None:
    settings = notifications.NotificationSettings(
        targets=["mobile_app_s24", "mobile_app_watch"], muted=["U7 Pro Wall"]
    )
    config = notifications.build(["sensor.b", "sensor.a"], settings)
    assert config["triggers"][0]["entity_id"] == ["sensor.a", "sensor.b"]
    assert [a["action"] for a in config["actions"]] == [
        "notify.mobile_app_s24",
        "notify.mobile_app_watch",
    ]
    parsed = notifications.parse(config)
    assert parsed.exists and parsed.targets == settings.targets and parsed.muted == settings.muted
    assert notifications.parse(None).exists is False


def test_device_label() -> None:
    assert notifications.device_label("mobile_app_s24_ultra_di_davide") == "S24 Ultra Di Davide"


def mock_ha_for_notifications(config_responses: list[httpx.Response]) -> dict[str, Any]:
    """Template endpoint answering both the tracker query and the automation lookup."""
    state = {"automation": "off"}

    def template(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)["template"]
        if "states.automation" in body:
            return httpx.Response(
                200,
                text=json.dumps({"entity_id": "automation.tracker", "state": state["automation"]}),
            )
        return httpx.Response(200, text=json.dumps(ROWS))

    def turn(new: str):  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            state["automation"] = new
            return httpx.Response(200, json=[])

        return handler

    respx.post(f"{BASE}/api/template").mock(side_effect=template)
    respx.get(f"{BASE}/api/services").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"domain": "light", "services": {"turn_on": {}}},
                {
                    "domain": "notify",
                    "services": {"mobile_app_s24": {}, "notify": {}, "mobile_app_watch": {}},
                },
            ],
        )
    )
    respx.get(f"{BASE}/api/config/automation/config/auto").mock(side_effect=config_responses)
    respx.post(f"{BASE}/api/services/automation/turn_on").mock(side_effect=turn("on"))
    respx.post(f"{BASE}/api/services/automation/turn_off").mock(side_effect=turn("off"))
    return state


@respx.mock
async def test_first_device_creates_and_enables_automation(ha: HomeAssistantClient) -> None:
    saved: list[dict[str, Any]] = []

    def save(request: httpx.Request) -> httpx.Response:
        saved.append(json.loads(request.content))
        return httpx.Response(200, json={"result": "ok"})

    respx.post(f"{BASE}/api/config/automation/config/auto").mock(side_effect=save)
    config_404 = httpx.Response(404, json={"message": "Resource not found"})
    state = mock_ha_for_notifications(
        [config_404, lambda request: httpx.Response(200, json=saved[-1])]  # type: ignore[list-item]
    )

    status = await TrackerService(ha, "auto").toggle_device("mobile_app_s24")

    assert state["automation"] == "on" and status.enabled
    assert status.devices == ["mobile_app_s24", "mobile_app_watch"]
    assert status.settings.targets == ["mobile_app_s24"]
    assert saved[-1]["actions"][0]["action"] == "notify.mobile_app_s24"
    assert len(saved[-1]["triggers"][0]["entity_id"]) == 4


@respx.mock
async def test_mute_product_and_disable(ha: HomeAssistantClient) -> None:
    existing = notifications.build(
        ["sensor.u7_wisp_prezzo"],
        notifications.NotificationSettings(targets=["mobile_app_s24"], muted=["Gone"]),
    )
    save = respx.post(f"{BASE}/api/config/automation/config/auto").mock(
        return_value=httpx.Response(200, json={"result": "ok"})
    )
    state = mock_ha_for_notifications([httpx.Response(200, json=existing)] * 6)
    service = TrackerService(ha, "auto")

    await service.toggle_product("U7 Pro Wall")
    muted = json.loads(save.calls.last.request.content)["triggers"][0]["variables"]["muted"]
    assert muted == ["U7 Pro Wall"]  # "Gone" is no longer tracked: forgotten

    state["automation"] = "on"
    await service.set_notifications(False)
    assert state["automation"] == "off"


@respx.mock
async def test_enable_without_devices_fails(ha: HomeAssistantClient) -> None:
    mock_ha_for_notifications([httpx.Response(404, json={})])
    with pytest.raises(TrackerError) as exc:
        await TrackerService(ha, "auto").set_notifications(True)
    assert exc.value.code == "no_devices"


def test_render_notifications() -> None:
    status = NotificationStatus(
        settings=notifications.NotificationSettings(
            targets=["mobile_app_s24"], muted=["U7 Pro Wall"], exists=True
        ),
        enabled=True,
        devices=["mobile_app_s24", "mobile_app_watch"],
        products=["Switch", "U7 Pro Wall"],
    )
    text, markup = render_notifications(status)
    assert "✅ S24" in text and "▫️ Watch" in text
    assert "🔕 U7 Pro Wall" in text and "🔔 Switch" in text
    data = [b.callback_data for r in markup.inline_keyboard for b in r]
    assert data[0] == "trn:off" and "trn:dev:1" in data and "trn:prod:1" in data


def test_price_notification_threshold_and_dots() -> None:
    config = notifications.build(
        ["sensor.a"], notifications.NotificationSettings(targets=["mobile_app_s24"])
    )
    conditions = " ".join(c["value_template"] for c in config["conditions"])
    assert f"abs >= {notifications.PRICE_THRESHOLD}" in conditions
    assert "delta" in config["triggers"][0]["variables"]
    title = config["actions"][0]["data"]["title"]
    assert "🔴" in title and "🟢" in title and "💶" not in title


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
