import pytest
from pydantic import ValidationError

from homegram.auth import command_name, is_allowed
from homegram.config import Settings


def make(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_id_lists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch, ALLOWED_USER_IDS="1, 2;3", ALLOWED_CHAT_IDS="-1001234567890")
    assert s.allowed_user_ids == {1, 2, 3}
    assert s.allowed_chat_ids == {-1001234567890}


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch)
    assert s.allowed_user_ids == frozenset()
    assert s.shopping_backend == "sqlite"
    assert not s.homeassistant_enabled
    assert s.database_path.name == "homegram.db"


def test_homeassistant_backend_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, SHOPPING_BACKEND="homeassistant")
    s = make(
        monkeypatch,
        SHOPPING_BACKEND="homeassistant",
        HA_URL="http://ha.local:8123",
        HA_TOKEN="secret",
    )
    assert s.homeassistant_enabled


def test_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch, ALLOWED_USER_IDS="10", ALLOWED_CHAT_IDS="-100")
    assert is_allowed(s, 10, 999)  # whitelisted user anywhere
    assert is_allowed(s, 42, -100)  # anyone in a whitelisted chat
    assert not is_allowed(s, 42, 999)
    assert not is_allowed(s, None, None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/id", "id"),
        ("/ID@HomeGramBot extra", "id"),
        ("hello", None),
        (None, None),
    ],
)
def test_command_name(text: str | None, expected: str | None) -> None:
    assert command_name(text) == expected
