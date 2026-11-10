import pytest
from telegram.ext import CommandHandler

from homegram.bot import build_application
from homegram.config import Settings
from homegram.features import FEATURES, enabled_features

TRACKER_COMMANDS = {"tracker", "tracker_aggiungi", "tracker_rimuovi", "tracker_notifiche"}


def registered_commands(app) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        cmd
        for handlers in app.handlers.values()
        for handler in handlers
        if isinstance(handler, CommandHandler)
        for cmd in handler.commands
    }


def test_application_registers_feature_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    app = build_application(Settings(_env_file=None))  # type: ignore[call-arg]

    registered = registered_commands(app)
    declared = {cmd for feature in enabled_features(False) for cmd, _ in feature.commands}
    assert declared <= registered
    assert {"start", "lista", "spesa", "bind"} <= registered
    # Without Home Assistant the tracker is not available at all.
    assert not TRACKER_COMMANDS & registered


def test_tracker_requires_home_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    monkeypatch.setenv("HA_URL", "http://ha.test:8123")
    monkeypatch.setenv("HA_TOKEN", "secret")
    app = build_application(Settings(_env_file=None))  # type: ignore[call-arg]

    declared = {cmd for feature in FEATURES for cmd, _ in feature.commands}
    assert declared <= registered_commands(app)
    assert registered_commands(app) >= TRACKER_COMMANDS


def test_feature_names_are_unique() -> None:
    names = [f.name for f in FEATURES]
    assert len(names) == len(set(names))
