"""Versioned schema migrations, applied in order at startup.

Never edit a migration that has been released: append a new one instead.
"""

from __future__ import annotations

import aiosqlite

MIGRATIONS: list[str] = [
    # v1 — topic bindings, shopping list, per-chat settings
    """
    CREATE TABLE topic_bindings (
        chat_id    INTEGER NOT NULL,
        thread_id  INTEGER NOT NULL DEFAULT 0,
        feature    TEXT    NOT NULL,
        created_by INTEGER,
        created_at TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (chat_id, thread_id, feature)
    );

    CREATE TABLE shopping_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id    INTEGER NOT NULL,
        text       TEXT    NOT NULL,
        done       INTEGER NOT NULL DEFAULT 0,
        added_by   INTEGER,
        created_at TEXT    NOT NULL DEFAULT (datetime('now')),
        done_at    TEXT
    );
    CREATE INDEX idx_shopping_items_chat_done ON shopping_items (chat_id, done);

    CREATE TABLE chat_settings (
        chat_id INTEGER NOT NULL,
        key     TEXT    NOT NULL,
        value   TEXT,
        PRIMARY KEY (chat_id, key)
    );
    """,
]


async def current_version(conn: aiosqlite.Connection) -> int:
    await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    async with conn.execute("SELECT MAX(version) FROM schema_version") as cur:
        row = await cur.fetchone()
    return int(row[0] or 0) if row else 0


async def migrate(conn: aiosqlite.Connection) -> int:
    """Apply pending migrations atomically. Returns the resulting schema version."""
    version = await current_version(conn)
    await conn.commit()
    for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        await conn.executescript(
            f"BEGIN;\n{sql}\nINSERT INTO schema_version (version) VALUES ({number});\nCOMMIT;"
        )
        version = number
    return version
