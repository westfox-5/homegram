"""Small data-access helpers on top of the shared SQLite connection."""

from __future__ import annotations

from dataclasses import dataclass

from homegram.db.database import Database


@dataclass(frozen=True)
class TopicBinding:
    chat_id: int
    thread_id: int
    feature: str


class TopicBindingRepo:
    """Which feature is attached to which forum topic (thread_id 0 = no topic / General)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def bind(self, chat_id: int, thread_id: int, feature: str, user_id: int | None) -> bool:
        cur = await self._db.conn.execute(
            "INSERT OR IGNORE INTO topic_bindings (chat_id, thread_id, feature, created_by) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, thread_id, feature, user_id),
        )
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def unbind(self, chat_id: int, thread_id: int, feature: str) -> bool:
        cur = await self._db.conn.execute(
            "DELETE FROM topic_bindings WHERE chat_id = ? AND thread_id = ? AND feature = ?",
            (chat_id, thread_id, feature),
        )
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def features_for(self, chat_id: int, thread_id: int) -> list[str]:
        async with self._db.conn.execute(
            "SELECT feature FROM topic_bindings WHERE chat_id = ? AND thread_id = ? "
            "ORDER BY feature",
            (chat_id, thread_id),
        ) as cur:
            return [row["feature"] for row in await cur.fetchall()]

    async def for_chat(self, chat_id: int) -> list[TopicBinding]:
        async with self._db.conn.execute(
            "SELECT chat_id, thread_id, feature FROM topic_bindings WHERE chat_id = ? "
            "ORDER BY feature, thread_id",
            (chat_id,),
        ) as cur:
            return [
                TopicBinding(r["chat_id"], r["thread_id"], r["feature"])
                for r in await cur.fetchall()
            ]

    async def for_feature(self, feature: str) -> list[TopicBinding]:
        """Every topic a feature is bound to: where its notifications go."""
        async with self._db.conn.execute(
            "SELECT chat_id, thread_id, feature FROM topic_bindings WHERE feature = ? "
            "ORDER BY chat_id, thread_id",
            (feature,),
        ) as cur:
            return [
                TopicBinding(r["chat_id"], r["thread_id"], r["feature"])
                for r in await cur.fetchall()
            ]

    async def set_topic_name(self, chat_id: int, thread_id: int, name: str) -> None:
        """Remember a topic's name (the Bot API has no call to look it up)."""
        await self._db.conn.execute(
            "INSERT INTO forum_topics (chat_id, thread_id, name) VALUES (?, ?, ?) "
            "ON CONFLICT (chat_id, thread_id) DO UPDATE SET name = excluded.name "
            "WHERE name != excluded.name",
            (chat_id, thread_id, name),
        )
        await self._db.conn.commit()

    async def topic_name(self, chat_id: int, thread_id: int) -> str | None:
        async with self._db.conn.execute(
            "SELECT name FROM forum_topics WHERE chat_id = ? AND thread_id = ?",
            (chat_id, thread_id),
        ) as cur:
            row = await cur.fetchone()
        return row["name"] if row else None


# chat_id used by ChatSettingsRepo for bot-wide settings.
GLOBAL_CHAT = 0


class ChatSettingsRepo:
    """Generic per-chat key/value store for small bits of feature state.

    Bot-wide settings use the chat id `GLOBAL_CHAT`.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, chat_id: int, key: str) -> str | None:
        async with self._db.conn.execute(
            "SELECT value FROM chat_settings WHERE chat_id = ? AND key = ?", (chat_id, key)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set(self, chat_id: int, key: str, value: str) -> None:
        await self._db.conn.execute(
            "INSERT INTO chat_settings (chat_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (chat_id, key) DO UPDATE SET value = excluded.value",
            (chat_id, key, value),
        )
        await self._db.conn.commit()

    async def delete(self, chat_id: int, key: str) -> None:
        await self._db.conn.execute(
            "DELETE FROM chat_settings WHERE chat_id = ? AND key = ?", (chat_id, key)
        )
        await self._db.conn.commit()
