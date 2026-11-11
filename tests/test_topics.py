from types import SimpleNamespace
from typing import Any

from homegram.db import Database, TopicBindingRepo
from homegram.features.topics import remember_topic_name, topic_label, topic_name_of


def message(**kwargs: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "chat_id": -1001234,
        "message_thread_id": 598,
        "is_topic_message": True,
        "forum_topic_created": None,
        "forum_topic_edited": None,
        "reply_to_message": None,
    }
    return SimpleNamespace(**{**defaults, **kwargs})


def created(name: str) -> SimpleNamespace:
    return message(forum_topic_created=SimpleNamespace(name=name))


def test_topic_name_of() -> None:
    assert topic_name_of(message(reply_to_message=created("Tracker"))) == "Tracker"
    assert topic_name_of(created("Casa")) == "Casa"
    assert topic_name_of(message(forum_topic_edited=SimpleNamespace(name="Nuovo"))) == "Nuovo"
    # A reply to a normal message, or a rename of the icon only, carries no name.
    assert topic_name_of(message(reply_to_message=message())) is None
    assert topic_name_of(message(forum_topic_edited=SimpleNamespace(name=None))) is None
    assert topic_name_of(None) is None


async def test_topic_label_uses_the_learned_name(db: Database) -> None:
    repo = TopicBindingRepo(db)
    assert await topic_label(repo, -1001234, 598) == (
        '<a href="https://t.me/c/1234/598">topic 598</a>'
    )
    await remember_topic_name(repo, message(reply_to_message=created("Tracker & co")))
    assert await topic_label(repo, -1001234, 598) == (
        '<a href="https://t.me/c/1234/598">Tracker &amp; co</a>'
    )
    assert await topic_label(repo, -1001234, 0) == "chat principale"
