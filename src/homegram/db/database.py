"""SQLite connection management. All bot state lives in a single file so it survives restarts."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

import aiosqlite

from homegram.db.migrations import migrate

log = logging.getLogger(__name__)


class DatabaseOpenError(RuntimeError):
    """The database file cannot be created or opened (usually a permissions problem)."""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.path)
        except (OSError, sqlite3.OperationalError) as exc:
            raise DatabaseOpenError(
                f"Cannot open the database at {self.path}: make sure {self.path.parent} "
                f"exists and is writable by uid {os.getuid()} (set DATA_DIR, or PUID/PGID "
                f"in Docker)"
            ) from exc
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        version = await migrate(self._conn)
        log.info("Database ready at %s (schema v%d)", self.path, version)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def healthcheck(self) -> bool:
        try:
            async with self.conn.execute("SELECT 1") as cur:
                return (await cur.fetchone()) is not None
        except Exception:
            log.exception("Database healthcheck failed")
            return False
