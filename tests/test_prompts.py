from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ApplicationHandlerStop

from homegram import prompts, strings
from homegram.context import CTX_KEY
from homegram.features.tracker import handlers as tracker
from homegram.features.tracker.service import Product, TrackedLink, TrackerError
from homegram.features.tracker.shops import WISP, UnsupportedUrl


def make_update(text: str = "", *, user_id: int = 1, thread_id: int = 0) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.is_topic_message = bool(thread_id)
    message.message_thread_id = thread_id or None
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = message
    update.effective_user = SimpleNamespace(id=user_id)
    update.effective_chat.send_action = AsyncMock()
    update.callback_query = None
    return update


def make_context(tracker_service: Any = None) -> MagicMock:
    context = MagicMock()
    context.chat_data = {}
    context.application.process_error = AsyncMock()
    context.application.bot_data = {CTX_KEY: SimpleNamespace(tracker=tracker_service)}
    return context


def last_reply(update: MagicMock) -> str:
    return update.effective_message.reply_text.call_args.args[0]


@pytest.fixture
def answers() -> list[tuple[str, dict[str, Any]]]:
    received: list[tuple[str, dict[str, Any]]] = []

    async def handler(update: Any, context: Any, text: str, data: dict[str, Any]) -> None:
        received.append((text, data))

    prompts.on_answer("test.ask", handler)
    return received


async def test_answer_goes_to_the_handler_once(answers: list[Any]) -> None:
    context = make_context()
    await prompts.ask(make_update("/cmd"), context, "test.ask", "Domanda?", value=42)

    with pytest.raises(ApplicationHandlerStop):  # consumed: no other handler sees it
        await prompts.on_text(make_update("  risposta "), context)
    assert answers == [("risposta", {"value": 42})]

    await prompts.on_text(make_update("altro testo"), context)  # no question: passes through
    assert len(answers) == 1


async def test_questions_are_per_user_and_topic(answers: list[Any]) -> None:
    context = make_context()
    await prompts.ask(make_update(user_id=1, thread_id=7), context, "test.ask", "?")

    await prompts.on_text(make_update("x", user_id=2, thread_id=7), context)
    await prompts.on_text(make_update("x", user_id=1, thread_id=0), context)
    assert answers == []
    with pytest.raises(ApplicationHandlerStop):
        await prompts.on_text(make_update("x", user_id=1, thread_id=7), context)
    assert len(answers) == 1


async def test_question_expires(answers: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    context = make_context()
    monkeypatch.setattr(prompts.time, "monotonic", lambda: 1000.0)
    await prompts.ask(make_update(), context, "test.ask", "?")
    monkeypatch.setattr(prompts.time, "monotonic", lambda: 1000.0 + prompts.TTL + 1)
    await prompts.on_text(make_update("tardi"), context)
    assert answers == []


async def test_other_command_and_cancel_drop_the_question(answers: list[Any]) -> None:
    context = make_context()
    await prompts.ask(make_update(), context, "test.ask", "?")
    await prompts.on_command(make_update("/tracker"), context)
    await prompts.on_text(make_update("x"), context)
    assert answers == []

    await prompts.ask(make_update(), context, "test.ask", "?")
    update = make_update("/annulla")
    with pytest.raises(ApplicationHandlerStop):
        await prompts.cancel_command(update, context)
    assert last_reply(update) == strings.PROMPT_CANCELLED
    with pytest.raises(ApplicationHandlerStop):
        await prompts.cancel_command(update, context)
    assert last_reply(update) == strings.PROMPT_NOTHING


async def test_handler_errors_are_reported_and_consumed() -> None:
    async def boom(*_: Any) -> None:
        raise RuntimeError("boom")

    prompts.on_answer("test.boom", boom)
    context = make_context()
    await prompts.ask(make_update(), context, "test.boom", "?")
    with pytest.raises(ApplicationHandlerStop):
        await prompts.on_text(make_update("x"), context)
    context.application.process_error.assert_awaited_once()


# --- /tracker_aggiungi without arguments ----------------------------------------------

URL = "https://wisp.store/p/1"
EXISTING = Product("U7 Pro Wall", [TrackedLink("e1", "https://www.amazon.it/dp/X", "U7", "Amazon")])


def fake_service(products: list[Product]) -> MagicMock:
    service = MagicMock()
    service.products = AsyncMock(return_value=products)
    service.find_product = AsyncMock(
        side_effect=lambda name: next(
            (p for p in products if p.name.casefold() == name.casefold()), None
        )
    )
    service.check_url = AsyncMock(return_value=(WISP, URL))
    link = TrackedLink("e2", URL, "x", "wisp.store", price=10.0)
    service.add = AsyncMock(side_effect=lambda name, url: (Product(name, [link]), link, True))
    return service


async def answer(context: MagicMock, text: str) -> MagicMock:
    update = make_update(text)
    with pytest.raises(ApplicationHandlerStop):
        await prompts.on_text(update, context)
    return update


async def test_add_new_product_step_by_step() -> None:
    service = fake_service([EXISTING])
    context = make_context(service)
    tracker.register_answers()

    update = make_update("/tracker_aggiungi")
    await tracker.add_command(update, context)
    assert "mandami il link" in last_reply(update)
    buttons = update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard
    assert buttons[0][0].callback_data == "trk:pick:e1"  # existing product, then cancel

    update = await answer(context, URL)
    service.check_url.assert_awaited_once_with(URL)
    assert "Come chiamo" in last_reply(update)

    update = await answer(context, "Alimentatore 210W")
    service.add.assert_awaited_once_with("Alimentatore 210W", URL)
    assert "Ora traccio <b>Alimentatore 210W</b>" in last_reply(update)


async def test_add_with_name_only_asks_for_the_link() -> None:
    service = fake_service([EXISTING])
    context = make_context(service)
    tracker.register_answers()

    update = make_update("/tracker_aggiungi u7 pro wall")
    await tracker.add_command(update, context)
    assert "un altro negozio per <b>U7 Pro Wall</b>" in last_reply(update)

    update = await answer(context, "non è un link")
    assert last_reply(update) == strings.TRACKER_ASK_LINK_AGAIN

    await answer(context, URL)
    service.add.assert_awaited_once_with("U7 Pro Wall", URL)


async def test_bad_link_is_asked_again() -> None:
    service = fake_service([])
    service.check_url.side_effect = [
        UnsupportedUrl("x"),
        TrackerError("duplicate_url", product="Altro"),
        (WISP, URL),
    ]
    context = make_context(service)
    tracker.register_answers()

    update = make_update("/tracker_aggiungi")
    await tracker.add_command(update, context)
    update = await answer(context, "https://example.com/x")
    assert "Link non supportato" in last_reply(update)
    update = await answer(context, URL)
    assert "già tracciato in <b>Altro</b>" in last_reply(update)
    update = await answer(context, URL)
    assert "Come chiamo" in last_reply(update)
    service.add.assert_not_awaited()


async def test_privacy_mode_asks_for_a_reply_in_groups(answers: list[Any]) -> None:
    context = make_context()
    update = make_update("/cmd")
    update.effective_chat.type = "supergroup"
    update.effective_chat.PRIVATE = "private"
    context.application.bot_data[prompts.READS_ALL_KEY] = False
    await prompts.ask(update, context, "test.ask", "Domanda?")
    assert last_reply(update) == "Domanda?" + strings.PROMPT_REPLY_HINT

    context.application.bot_data[prompts.READS_ALL_KEY] = True
    await prompts.ask(update, context, "test.ask", "Domanda?")
    assert last_reply(update) == "Domanda?"
