import pytest
from telegram.ext import CommandHandler

from homegram.bot import build_application
from homegram.config import Settings
from homegram.features import FEATURES


def test_application_registers_all_feature_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    app = build_application(Settings(_env_file=None))  # type: ignore[call-arg]

    registered = {
        cmd
        for handlers in app.handlers.values()
        for handler in handlers
        if isinstance(handler, CommandHandler)
        for cmd in handler.commands
    }
    declared = {cmd for feature in FEATURES for cmd, _ in feature.commands}
    assert declared <= registered
    assert {"start", "lista", "spesa", "bind"} <= registered


def test_feature_names_are_unique() -> None:
    names = [f.name for f in FEATURES]
    assert len(names) == len(set(names))
