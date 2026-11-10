"""Price tracker: /tracker, /tracker_aggiungi, /tracker_rimuovi, /tracker_notifiche.

Requires Home Assistant (scrape integration, companion app for notifications).
"""

from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from homegram import strings
from homegram.context import get_ctx
from homegram.features.base import Feature
from homegram.features.tracker.notifications import device_label
from homegram.features.tracker.service import (
    NotificationStatus,
    Product,
    TrackedLink,
    TrackerError,
    TrackerService,
)
from homegram.features.tracker.shops import SHOPS, UnsupportedUrl
from homegram.integrations.homeassistant import HomeAssistantError

log = logging.getLogger(__name__)

FEATURE_NAME = "tracker"
CALLBACK_PREFIX = "trk"
NOTIFY_PREFIX = "trn"
BUTTON_LABEL_LENGTH = 40
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _service(context: ContextTypes.DEFAULT_TYPE) -> TrackerService:
    tracker = get_ctx(context).tracker
    assert tracker is not None, "the tracker feature is only registered with Home Assistant"
    return tracker


def _truncate(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def format_price(value: float | None) -> str:
    if value is None:
        return strings.TRACKER_NO_PRICE
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def format_stock(link: TrackedLink) -> str:
    available = link.available
    if available is None:
        return strings.TRACKER_STOCK_UNKNOWN
    if not available:
        return strings.TRACKER_STOCK_OUT
    stock = (link.stock or "").strip()
    if link.stock_unit:
        stock = f"{stock} {link.stock_unit}"
    for prefix in ("Disponibilità:", "Disponibilità"):
        stock = stock.removeprefix(prefix).strip()
    return f"✅ {html.escape(_truncate(stock, 40))}"


def render_link(link: TrackedLink, best: TrackedLink | None) -> str:
    price = format_price(link.price)
    if best is not None and link.entry_id == best.entry_id:
        price = f"<b>{price}</b>"
    shop = f'<a href="{html.escape(link.url, quote=True)}">{html.escape(link.shop)}</a>'
    return f"  • {shop}: {price} · {format_stock(link)}"


def render_product(product: Product) -> list[str]:
    best = product.best
    return [f"<b>{html.escape(product.name)}</b>"] + [
        render_link(link, best) for link in product.links
    ]


def render_products(products: list[Product]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not products:
        return strings.TRACKER_EMPTY, None
    lines = [strings.TRACKER_TITLE.format(count=len(products))]
    rows = []
    for product in products:
        lines.append("")
        lines += render_product(product)
        for link in product.links:
            label = f"🗑 {_truncate(product.name, BUTTON_LABEL_LENGTH)} · {link.shop}"
            rows.append(
                [InlineKeyboardButton(label, callback_data=f"{CALLBACK_PREFIX}:rm:{link.entry_id}")]
            )
    lines += ["", strings.TRACKER_FOOTER]
    rows.append(
        [InlineKeyboardButton(strings.TRACKER_BTN_REFRESH, callback_data=f"{CALLBACK_PREFIX}:ls")]
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def supported_shops() -> str:
    return ", ".join(shop.name for shop in SHOPS)


def split_args(text: str | None) -> tuple[str, str | None]:
    """Split command arguments into (product name, URL). The URL may be anywhere."""
    words = (text or "").split()[1:]
    url = next((w for w in words if w.lower().startswith(("http://", "https://"))), None)
    name = " ".join(w for w in words if w is not url)
    return name, url


def error_text(exc: TrackerError) -> str:
    details = {k: html.escape(str(v)) for k, v in exc.details.items()}
    template = {
        "empty_name": strings.TRACKER_USAGE,
        "long_name": strings.TRACKER_ERR_LONG_NAME,
        "duplicate_url": strings.TRACKER_ERR_DUPLICATE_URL,
        "duplicate_shop": strings.TRACKER_ERR_DUPLICATE_SHOP,
        "flow_failed": strings.TRACKER_ERR_FLOW,
        "no_devices": strings.TRACKER_ERR_NO_DEVICES,
        "no_products": strings.TRACKER_ERR_NO_PRODUCTS,
        "notifications_disabled": strings.TRACKER_ERR_NOTIFY_DISABLED,
    }.get(exc.code, strings.GENERIC_ERROR)
    return template.format(shops=supported_shops(), **details)


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=markup, link_preview_options=NO_PREVIEW
    )


async def _guard_ha(update: Update, exc: HomeAssistantError) -> None:
    if exc.forbidden:
        await _reply(update, strings.TRACKER_ERR_FORBIDDEN)
        return
    raise exc


async def tracker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        text, markup = render_products(await _service(context).products())
    except HomeAssistantError as exc:
        await _guard_ha(update, exc)
        return
    await _reply(update, text, markup)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name, url = split_args(update.effective_message.text)
    if not name or not url:
        await _reply(update, strings.TRACKER_USAGE.format(shops=supported_shops()))
        return

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        product, link, created = await _service(context).add(name, url)
    except UnsupportedUrl:
        await _reply(update, strings.TRACKER_ERR_SHOP.format(shops=supported_shops()))
        return
    except TrackerError as exc:
        await _reply(update, error_text(exc))
        return
    except HomeAssistantError as exc:
        await _guard_ha(update, exc)
        return

    template = strings.TRACKER_ADDED_PRODUCT if created else strings.TRACKER_ADDED_LINK
    lines = [template.format(product=html.escape(product.name), shop=html.escape(link.shop))]
    lines += render_product(product)
    if link.price is None:
        lines += ["", strings.TRACKER_NO_VALUE_YET]
    await _reply(update, "\n".join(lines))


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name, _ = split_args(update.effective_message.text)
    if not name:
        await _reply(update, strings.TRACKER_REMOVE_USAGE)
        return
    try:
        product = await _service(context).find_product(name)
    except HomeAssistantError as exc:
        await _guard_ha(update, exc)
        return
    if product is None:
        await _reply(update, strings.TRACKER_NOT_FOUND.format(product=html.escape(name)))
        return
    entry_id = product.links[0].entry_id
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    strings.TRACKER_BTN_CONFIRM, callback_data=f"{CALLBACK_PREFIX}:rmp:{entry_id}"
                ),
                InlineKeyboardButton(
                    strings.TRACKER_BTN_CANCEL, callback_data=f"{CALLBACK_PREFIX}:no"
                ),
            ]
        ]
    )
    await _reply(
        update,
        strings.TRACKER_CONFIRM_PRODUCT.format(
            product=html.escape(product.name), count=len(product.links)
        ),
        markup,
    )


def _confirm_link_markup(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    strings.TRACKER_BTN_CONFIRM, callback_data=f"{CALLBACK_PREFIX}:rmok:{entry_id}"
                ),
                InlineKeyboardButton(
                    strings.TRACKER_BTN_CANCEL, callback_data=f"{CALLBACK_PREFIX}:ls"
                ),
            ]
        ]
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.message is None or not query.data:
        await query.answer()
        return
    service = _service(context)
    _, action, *rest = query.data.split(":", 2)
    entry_id = rest[0] if rest else ""

    try:
        if action == "rm":
            # First tap: ask for confirmation on the same message.
            await query.answer(strings.TRACKER_CONFIRM_LINK)
            await query.edit_message_reply_markup(_confirm_link_markup(entry_id))
            return
        if action == "no":
            await query.answer()
            await query.edit_message_text(strings.TRACKER_CANCELLED)
            return
        if action == "rmp":
            product = await service.remove_product(entry_id)
            if product is None:
                await query.answer(strings.TRACKER_GONE, show_alert=True)
            else:
                await query.answer(strings.TRACKER_REMOVED_TOAST)
            text = (
                strings.TRACKER_REMOVED_PRODUCT.format(product=html.escape(product.name))
                if product
                else strings.TRACKER_GONE
            )
            await query.edit_message_text(text, parse_mode=ParseMode.HTML)
            return

        toast: str | None = None
        if action == "rmok":
            link = await service.remove_link(entry_id)
            toast = strings.TRACKER_REMOVED_TOAST if link else strings.TRACKER_GONE
        await query.answer(toast)
        text, markup = render_products(await service.products())
    except HomeAssistantError as exc:
        text = strings.TRACKER_ERR_FORBIDDEN if exc.forbidden else strings.HA_UNAVAILABLE
        await query.answer(_strip_tags(text), show_alert=True)
        return

    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup, link_preview_options=NO_PREVIEW
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def _strip_tags(text: str) -> str:
    for tag in ("<b>", "</b>", "<code>", "</code>", "<i>", "</i>"):
        text = text.replace(tag, "")
    return html.unescape(text)


# --- notifications ------------------------------------------------------------------


def render_notifications(status: NotificationStatus) -> tuple[str, InlineKeyboardMarkup]:
    targets = set(status.settings.targets)
    muted = set(status.settings.muted)
    lines = [strings.TRACKER_NOTIFY_ON if status.enabled else strings.TRACKER_NOTIFY_OFF, ""]
    lines.append(strings.TRACKER_NOTIFY_HELP)

    rows: list[list[InlineKeyboardButton]] = []
    if status.enabled:
        toggle = (strings.TRACKER_BTN_NOTIFY_OFF, f"{NOTIFY_PREFIX}:off")
    else:
        toggle = (strings.TRACKER_BTN_NOTIFY_ON, f"{NOTIFY_PREFIX}:on")
    rows.append([InlineKeyboardButton(toggle[0], callback_data=toggle[1])])

    lines += ["", strings.TRACKER_NOTIFY_DEVICES]
    if not status.devices:
        lines.append(strings.TRACKER_NOTIFY_NO_DEVICES)
    for index, device in enumerate(status.devices):
        mark = "✅" if device in targets else "▫️"
        label = html.escape(device_label(device))
        lines.append(f"{mark} {label}")
        rows.append(
            [
                InlineKeyboardButton(
                    f"📱 {mark} {_truncate(device_label(device), BUTTON_LABEL_LENGTH)}",
                    callback_data=f"{NOTIFY_PREFIX}:dev:{index}",
                )
            ]
        )

    lines += ["", strings.TRACKER_NOTIFY_PRODUCTS]
    if not status.products:
        lines.append(strings.TRACKER_NOTIFY_NO_PRODUCTS)
    product_buttons = []
    for index, product in enumerate(status.products):
        mark = "🔕" if product in muted else "🔔"
        lines.append(f"{mark} {html.escape(product)}")
        product_buttons.append(
            InlineKeyboardButton(
                f"{mark} {_truncate(product, BUTTON_LABEL_LENGTH // 2)}",
                callback_data=f"{NOTIFY_PREFIX}:prod:{index}",
            )
        )
    rows += [product_buttons[i : i + 2] for i in range(0, len(product_buttons), 2)]
    rows.append(
        [InlineKeyboardButton(strings.TRACKER_BTN_REFRESH, callback_data=f"{NOTIFY_PREFIX}:ls")]
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        status = await _service(context).notification_status()
    except TrackerError as exc:
        await _reply(update, error_text(exc))
        return
    except HomeAssistantError as exc:
        await _guard_ha(update, exc)
        return
    text, markup = render_notifications(status)
    await _reply(update, text, markup)


async def on_notify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.message is None or not query.data:
        await query.answer()
        return
    service = _service(context)
    _, action, *rest = query.data.split(":", 2)
    try:
        status = await service.notification_status()
        index = int(rest[0]) if rest and rest[0].isdigit() else -1
        if action == "dev" and 0 <= index < len(status.devices):
            status = await service.toggle_device(status.devices[index])
        elif action == "prod" and 0 <= index < len(status.products):
            status = await service.toggle_product(status.products[index])
        elif action in ("on", "off"):
            status = await service.set_notifications(action == "on")
    except TrackerError as exc:
        await query.answer(_strip_tags(error_text(exc)), show_alert=True)
        return
    except HomeAssistantError as exc:
        text = strings.TRACKER_ERR_FORBIDDEN if exc.forbidden else strings.HA_UNAVAILABLE
        await query.answer(_strip_tags(text), show_alert=True)
        return
    await query.answer()
    text, markup = render_notifications(status)
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def register(app: Application) -> None:
    app.add_handler(CommandHandler("tracker", tracker_command))
    app.add_handler(CommandHandler("tracker_aggiungi", add_command))
    app.add_handler(CommandHandler("tracker_rimuovi", remove_command))
    app.add_handler(CommandHandler("tracker_notifiche", notifications_command))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=rf"^{CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(on_notify_callback, pattern=rf"^{NOTIFY_PREFIX}:"))


FEATURE = Feature(
    name=FEATURE_NAME,
    description="Tracker di prezzi e disponibilità (Home Assistant)",
    register=register,
    commands=[
        ("tracker", "prezzi e disponibilità dei prodotti tracciati"),
        ("tracker_aggiungi", "traccia un prodotto, es. /tracker_aggiungi U7 Pro Wall <link>"),
        ("tracker_rimuovi", "smetti di tracciare un prodotto, es. /tracker_rimuovi U7 Pro Wall"),
        ("tracker_notifiche", "notifiche: dispositivi, prodotti, on/off"),
    ],
    requires_homeassistant=True,
)
