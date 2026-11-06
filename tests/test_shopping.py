from pathlib import Path

import pytest

from homegram.db import Database
from homegram.features.shopping.backends import ShoppingItem, SqliteShoppingBackend
from homegram.features.shopping.handlers import MAX_SHOWN, parse_items, render_list


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("latte", ["latte"]),
        ("latte, uova;pane", ["latte", "uova", "pane"]),
        ("- latte\n- uova\n\n1. pane\n2) burro", ["latte", "uova", "pane", "burro"]),
        ("  ,  ,", []),
        ("", []),
        (None, []),
    ],
)
def test_parse_items(text: str | None, expected: list[str]) -> None:
    assert parse_items(text) == expected


def test_parse_items_truncates_long_items() -> None:
    assert len(parse_items("x" * 1000)[0]) == 200


def test_render_empty_list() -> None:
    text, markup = render_list([])
    assert "vuota" in text
    assert len(markup.inline_keyboard) == 1  # only refresh/clear


def test_render_list_escapes_and_limits() -> None:
    items = [ShoppingItem(str(i), f"<item {i}>") for i in range(MAX_SHOWN + 5)]
    text, markup = render_list(items)
    assert "&lt;item 0&gt;" in text
    assert "altri 5" in text
    assert len(markup.inline_keyboard) == MAX_SHOWN + 1
    assert markup.inline_keyboard[0][0].callback_data == "shop:done:0"


async def test_sqlite_backend_flow(db: Database) -> None:
    backend = SqliteShoppingBackend(db)
    await backend.add(1, ["latte", "uova"], user_id=10)
    await backend.add(2, ["pane"], user_id=10)

    items = await backend.list_open(1)
    assert [i.text for i in items] == ["latte", "uova"]
    assert [i.text for i in await backend.list_open(2)] == ["pane"]

    assert await backend.complete(1, items[0].id) is True
    assert await backend.complete(1, items[0].id) is False  # already done
    assert await backend.complete(2, items[1].id) is False  # other chat
    assert await backend.complete(1, "not-a-number") is False
    assert [i.text for i in await backend.list_open(1)] == ["uova"]

    assert await backend.clear_completed(1) == 1
    assert await backend.clear_completed(1) == 0


async def test_shopping_list_survives_restart(db_path: Path) -> None:
    first = Database(db_path)
    await first.connect()
    await SqliteShoppingBackend(first).add(1, ["latte"], user_id=None)
    await first.close()

    second = Database(db_path)
    await second.connect()
    try:
        assert [i.text for i in await SqliteShoppingBackend(second).list_open(1)] == ["latte"]
    finally:
        await second.close()
