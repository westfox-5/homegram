import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from homegram.features.shopping.backends import HomeAssistantShoppingBackend
from homegram.integrations.homeassistant import HomeAssistantClient, HomeAssistantError

BASE = "http://ha.test:8123"
ENTITY = "todo.shopping_list"


@pytest.fixture
async def client() -> AsyncIterator[HomeAssistantClient]:
    c = HomeAssistantClient(BASE + "/", "secret-token")
    yield c
    await c.close()


def items_response(*items: tuple[str, str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "changed_states": [],
            "service_response": {
                ENTITY: {
                    "items": [
                        {"uid": uid, "summary": summary, "status": "needs_action"}
                        for uid, summary in items
                    ]
                }
            },
        },
    )


@respx.mock
async def test_ping_sends_token(client: HomeAssistantClient) -> None:
    route = respx.get(f"{BASE}/api/").mock(
        return_value=httpx.Response(200, json={"message": "API running."})
    )
    assert await client.ping() is True
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@respx.mock
async def test_errors_are_wrapped(client: HomeAssistantClient) -> None:
    respx.get(f"{BASE}/api/").mock(return_value=httpx.Response(401))
    with pytest.raises(HomeAssistantError):
        await client.ping()
    respx.get(f"{BASE}/api/").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(HomeAssistantError):
        await client.ping()


@respx.mock
async def test_todo_items(client: HomeAssistantClient) -> None:
    route = respx.post(f"{BASE}/api/services/todo/get_items?return_response").mock(
        return_value=items_response(("a1", "latte"))
    )
    items = await client.todo_items(ENTITY)
    assert items[0]["summary"] == "latte"
    assert json.loads(route.calls.last.request.content) == {
        "entity_id": ENTITY,
        "status": ["needs_action"],
    }


@respx.mock
async def test_unexpected_response_raises(client: HomeAssistantClient) -> None:
    respx.post(f"{BASE}/api/services/todo/get_items?return_response").mock(
        return_value=httpx.Response(200, json={"oops": True})
    )
    with pytest.raises(HomeAssistantError):
        await client.todo_items(ENTITY)


@respx.mock
async def test_ha_shopping_backend(client: HomeAssistantClient) -> None:
    respx.post(f"{BASE}/api/services/todo/get_items?return_response").mock(
        return_value=items_response(("a1", "latte"), ("b2", "uova"))
    )
    add = respx.post(f"{BASE}/api/services/todo/add_item").mock(
        return_value=httpx.Response(200, json=[])
    )
    update = respx.post(f"{BASE}/api/services/todo/update_item").mock(
        return_value=httpx.Response(200, json=[])
    )
    clear = respx.post(f"{BASE}/api/services/todo/remove_completed_items").mock(
        return_value=httpx.Response(200, json=[])
    )
    backend = HomeAssistantShoppingBackend(client, ENTITY)

    assert [i.text for i in await backend.list_open(1)] == ["latte", "uova"]

    await backend.add(1, ["pane", "burro"], user_id=None)
    assert add.call_count == 2
    assert json.loads(add.calls.last.request.content) == {"entity_id": ENTITY, "item": "burro"}

    assert await backend.complete(1, "a1") is True
    assert json.loads(update.calls.last.request.content) == {
        "entity_id": ENTITY,
        "item": "a1",
        "status": "completed",
    }
    assert await backend.complete(1, "missing") is False
    assert update.call_count == 1

    assert await backend.clear_completed(1) is None
    assert clear.called
