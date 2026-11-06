from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from homegram.db import Database


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "homegram.db"


@pytest.fixture
async def db(db_path: Path) -> AsyncIterator[Database]:
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()
