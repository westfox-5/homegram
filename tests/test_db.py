from pathlib import Path

import pytest

from homegram.db import ChatSettingsRepo, Database, TopicBinding, TopicBindingRepo
from homegram.db.database import DatabaseOpenError
from homegram.db.migrations import MIGRATIONS, current_version, migrate


async def test_migrations_are_idempotent(db: Database) -> None:
    assert await current_version(db.conn) == len(MIGRATIONS)
    assert await migrate(db.conn) == len(MIGRATIONS)


async def test_topic_bindings(db: Database) -> None:
    repo = TopicBindingRepo(db)
    assert await repo.bind(-100, 7, "spesa", 1) is True
    assert await repo.bind(-100, 7, "spesa", 1) is False
    assert await repo.features_for(-100, 7) == ["spesa"]
    assert await repo.features_for(-100, 8) == []
    assert await repo.for_chat(-100) == [TopicBinding(-100, 7, "spesa")]
    assert await repo.unbind(-100, 7, "spesa") is True
    assert await repo.unbind(-100, 7, "spesa") is False
    assert await repo.features_for(-100, 7) == []


async def test_chat_settings(db: Database) -> None:
    repo = ChatSettingsRepo(db)
    assert await repo.get(1, "k") is None
    await repo.set(1, "k", "a")
    await repo.set(1, "k", "b")
    assert await repo.get(1, "k") == "b"
    assert await repo.get(2, "k") is None
    await repo.delete(1, "k")
    assert await repo.get(1, "k") is None


async def test_state_survives_restart(db_path: Path) -> None:
    first = Database(db_path)
    await first.connect()
    await TopicBindingRepo(first).bind(-100, 7, "spesa", 1)
    await first.close()

    second = Database(db_path)
    await second.connect()
    try:
        assert await TopicBindingRepo(second).features_for(-100, 7) == ["spesa"]
    finally:
        await second.close()


async def test_unusable_path_gives_a_clear_error(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("")
    with pytest.raises(DatabaseOpenError, match="writable"):
        await Database(not_a_dir / "homegram.db").connect()


async def test_topic_names(db: Database) -> None:
    repo = TopicBindingRepo(db)
    assert await repo.topic_name(-100, 598) is None
    await repo.set_topic_name(-100, 598, "Tracker")
    await repo.set_topic_name(-100, 598, "Tracker prezzi")  # renamed
    assert await repo.topic_name(-100, 598) == "Tracker prezzi"
