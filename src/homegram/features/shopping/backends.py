"""Shopping list storage backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from homegram.db.database import Database
from homegram.integrations.homeassistant import HomeAssistantClient


@dataclass(frozen=True)
class ShoppingItem:
    id: str
    text: str


class ShoppingBackend(Protocol):
    async def list_open(self, chat_id: int) -> list[ShoppingItem]: ...

    async def add(self, chat_id: int, texts: list[str], user_id: int | None) -> None: ...

    async def complete(self, chat_id: int, item_id: str) -> bool: ...

    async def clear_completed(self, chat_id: int) -> int | None:
        """Remove completed items. Returns how many were removed, if known."""
        ...


class SqliteShoppingBackend:
    """Default backend: one list per Telegram chat, stored in the bot's SQLite database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_open(self, chat_id: int) -> list[ShoppingItem]:
        async with self._db.conn.execute(
            "SELECT id, text FROM shopping_items WHERE chat_id = ? AND done = 0 ORDER BY id",
            (chat_id,),
        ) as cur:
            return [ShoppingItem(str(r["id"]), r["text"]) for r in await cur.fetchall()]

    async def add(self, chat_id: int, texts: list[str], user_id: int | None) -> None:
        await self._db.conn.executemany(
            "INSERT INTO shopping_items (chat_id, text, added_by) VALUES (?, ?, ?)",
            [(chat_id, text, user_id) for text in texts],
        )
        await self._db.conn.commit()

    async def complete(self, chat_id: int, item_id: str) -> bool:
        if not item_id.isdigit():
            return False
        cur = await self._db.conn.execute(
            "UPDATE shopping_items SET done = 1, done_at = datetime('now') "
            "WHERE id = ? AND chat_id = ? AND done = 0",
            (int(item_id), chat_id),
        )
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def clear_completed(self, chat_id: int) -> int | None:
        cur = await self._db.conn.execute(
            "DELETE FROM shopping_items WHERE chat_id = ? AND done = 1", (chat_id,)
        )
        await self._db.conn.commit()
        return cur.rowcount


class HomeAssistantShoppingBackend:
    """Uses a Home Assistant to-do entity. The list is shared by every chat."""

    def __init__(self, client: HomeAssistantClient, entity_id: str) -> None:
        self._client = client
        self._entity = entity_id

    async def list_open(self, chat_id: int) -> list[ShoppingItem]:
        items = await self._client.todo_items(self._entity)
        return [ShoppingItem(str(i["uid"]), str(i["summary"])) for i in items if "uid" in i]

    async def add(self, chat_id: int, texts: list[str], user_id: int | None) -> None:
        for text in texts:
            await self._client.todo_add(self._entity, text)

    async def complete(self, chat_id: int, item_id: str) -> bool:
        open_ids = {item.id for item in await self.list_open(chat_id)}
        if item_id not in open_ids:
            return False
        await self._client.todo_complete(self._entity, item_id)
        return True

    async def clear_completed(self, chat_id: int) -> int | None:
        await self._client.todo_remove_completed(self._entity)
        return None
