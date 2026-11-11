# 🏠 HomeGram

A small, modular Telegram bot for your home. Add it to your household group chat (forum **topics** supported) and use it for everyday home stuff.

**Features (v0.1)**

- 🛒 **Shared shopping list**: add items with `/spesa_aggiungi`, see the list with `/spesa`, tick them off with inline buttons, clear completed ones.
- 📌 **Topic bindings**: attach a feature to a forum topic. In a topic bound to the shopping list, *any* message is added to the list.
- 💾 **Persistent state** in a single SQLite file: survives restarts and upgrades.
- 🏡 **Optional Home Assistant integration**: use a Home Assistant to-do entity as the shopping list.
- 📈 **Price tracker** *(Home Assistant only)*: track prices and stock of products across shops with `/tracker_aggiungi`; the bot creates the scrapers in Home Assistant for you and can push changes to your phone.
- 🔒 **Whitelist** of users and chats.

Commands are grouped by feature: each feature has a main command (`/spesa`, `/tracker`) and sub-commands prefixed with its name (`/spesa_aggiungi`, `/tracker_aggiungi`, …). The old `/lista` and `/spesa <items>` still work as aliases.

The bot's messages are in Italian (all texts live in [`src/homegram/strings.py`](src/homegram/strings.py), so you can translate them).

## Commands

| Command | Description |
| --- | --- |
| `/help` | List commands and the features active in the current topic |
| `/ping` | Check that the bot, the database and Home Assistant (if configured) are working |
| `/id` | Show chat, topic and user ids (available to everyone, useful for setup) |
| `/bind <feature>` | Attach a feature to the current topic (e.g. `/bind spesa`) |
| `/unbind <feature>` | Detach a feature from the current topic |
| `/bindings` | List the topic bindings of this chat |
| `/spesa` | Show the shopping list with ✅ buttons |
| `/spesa_aggiungi latte, uova` | Add one or more items (commas, semicolons or new lines separate them) |
| `/tracker` | Prices and stock of the tracked products, with 🗑 buttons to remove a shop *(Home Assistant only)* |
| `/tracker_aggiungi <product> <link>` | Track a product page. With the name of a product already tracked, adds another shop *(Home Assistant only)* |
| `/tracker_rimuovi <product>` | Stop tracking a product and delete all its scrapers *(Home Assistant only)* |
| `/tracker_notifiche` | Choose which devices get notified and for which products, or turn notifications off *(Home Assistant only)* |

## Quick start

### 1. Create the bot

1. Talk to [@BotFather](https://t.me/BotFather), run `/newbot` and copy the token.
2. Run `/setprivacy` → choose your bot → **Disable**. This lets the bot read normal messages in a bound topic (otherwise it only sees commands).
3. Add the bot to your group.

### 2. Configure

```bash
git clone https://github.com/westfox-5/homegram.git
cd homegram
cp .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` in `.env`. To find the ids to allow, start the bot and send `/id` in the group (or in a private chat with the bot), then fill in:

- `ALLOWED_CHAT_IDS`: your group id (e.g. `-1001234567890`). Everyone in the group can use the bot.
- `ALLOWED_USER_IDS`: users allowed anywhere, including private chats with the bot.

Restart the bot after changing `.env`.

### 3. Run with Docker

The compose file runs the prebuilt image from GHCR (`linux/amd64` and `linux/arm64`). Everything is configured through `.env`; nothing is baked into the image.

```bash
docker compose up -d
docker compose logs -f
```

Pin a version with `HOMEGRAM_VERSION=0.1.0-alpha.1` in `.env`, or build from source with `docker compose build`.

### 4. Set up topics

In your group, open the topic you want to use for groceries (e.g. "🛒 Spesa") and send:

```
/bind spesa
```

From now on, every message written in that topic is added to the list (the bot reacts with 👍). Use `/spesa` to see it and tick items off.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | Bot token from BotFather (required) |
| `ALLOWED_USER_IDS` | empty | Comma-separated Telegram user ids |
| `ALLOWED_CHAT_IDS` | empty | Comma-separated chat ids |
| `DATA_DIR` | `/data` | Folder holding `homegram.db` (used with every backend) |
| `PUID` / `PGID` | `1000` | Docker only: user/group the bot runs as; `DATA_DIR` is chown'ed to them at startup, so bind mounts owned by root work |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SHOPPING_BACKEND` | `sqlite` | `sqlite` (one list per chat) or `homeassistant` |
| `HA_URL` | — | e.g. `http://homeassistant.local:8123` |
| `HA_TOKEN` | — | Home Assistant long-lived access token |
| `HA_SHOPPING_ENTITY` | `todo.shopping_list` | To-do entity used by the `homeassistant` backend |
| `HA_TRACKER_AUTOMATION` | `tracker_notifica` | Id of the Home Assistant automation the price tracker generates for notifications (see below). Empty to disable notifications |
| `HOMEGRAM_VERSION` | `latest` | Image tag used by `docker-compose.yml` |

If both whitelists are empty, the bot ignores everyone except for `/id`.

## Home Assistant (optional)

1. In Home Assistant, open your profile → **Security** → **Long-lived access tokens** → create one.
2. Make sure you have a to-do list entity, e.g. the built-in **Shopping List** integration (`todo.shopping_list`).
3. Set `HA_URL`, `HA_TOKEN` and `SHOPPING_BACKEND=homeassistant` in `.env`, then `docker compose up -d`.

`HA_URL` must be reachable from inside the HomeGram container:

| Where Home Assistant runs | `HA_URL` |
| --- | --- |
| Same host, e.g. a container with `network_mode: host` | `http://host.docker.internal:8123` (mapped by `extra_hosts` in `docker-compose.yml`) |
| Same compose project / Docker network | `http://<service-name>:8123` |
| Another machine on the LAN | `http://<ip>:8123` |

The list is then shared with the Home Assistant app and every chat. `/ping` reports whether Home Assistant is reachable.

## Price tracker (Home Assistant)

> [!IMPORTANT]
> The price tracker works **only when the bot is connected to Home Assistant** (`HA_URL` and `HA_TOKEN` set). Without them the `/tracker*` commands are not registered and do not appear in the command menu.
> The token must belong to a Home Assistant **administrator**: the bot creates and deletes [Scrape](https://www.home-assistant.io/integrations/scrape/) integrations, which requires admin rights.

```
/tracker_aggiungi U7 Pro Wall https://wisp.store/unifi/10765-ubiquiti-unifi-u7-pro-wall-u7-pro-wall.html
/tracker_aggiungi U7 Pro Wall https://www.amazon.it/dp/B0D9JTNXNL
/tracker
/tracker_notifiche
/tracker_rimuovi U7 Pro Wall
```

Supported shops: **wisp.store** and **Amazon** (`.it`, `.de`, `.fr`, `.es`). Amazon app share links (`https://amzn.eu/d/…`, `amzn.to`, `a.co`) work too: the bot follows the redirect to the product page. Shop profiles (URL normalization and CSS selectors) live in [`src/homegram/features/tracker/shops.py`](src/homegram/features/tracker/shops.py).

How it works:

- Each link is a Scrape config entry in Home Assistant (its title is the product URL) with two sensors named `<product> · <shop> · prezzo` and `<product> · <shop> · disponibilità`. Home Assistant is the only source of truth: nothing about the tracker is stored in the bot's database.
- Home Assistant polls each page every ~10 minutes. Some shops (Amazon) may start blocking requests: the price sensor then becomes *unavailable* instead of showing a wrong value.
- Dashboards and automations can find every tracked product through the same naming convention, e.g. in a template: `integration_entities('scrape')` + `state_attr(e, 'friendly_name').split(' · ')`, and the URL with `config_entry_attr(config_entry_id(e), 'title')`.
- **Notifications**: `/tracker_notifiche` lets you pick the devices (every phone or watch with the Home Assistant companion app, i.e. the `notify.mobile_app_*` services), mute single products and turn notifications on or off. A notification is sent when a price changes by at least 5 € (🔴 up, 🟢 down) or a product goes in or out of stock (not for every piece sold). The bot generates a Home Assistant automation for this (id `tracker_notifica`, see `HA_TRACKER_AUTOMATION`) and rewrites it whenever products or settings change and when the bot starts, so don't edit it by hand. The settings live in the automation itself: the notify actions are the devices, the `muted` trigger variable lists the muted products, and the automation's on/off state is the main switch.

## Data and backups

All the bot's state (topic bindings, the SQLite shopping list, small per-chat settings) is stored in `homegram.db` inside the `homegram-data` Docker volume. Schema migrations run automatically at startup, so upgrading the image keeps your data.

Backup:

```bash
docker compose exec homegram python -c "import sqlite3; sqlite3.connect('/data/homegram.db').backup(sqlite3.connect('/data/backup.db'))"
docker compose cp homegram:/data/backup.db ./homegram-backup.db
```

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run python -m homegram   # reads .env from the current directory
```

When running locally, set `DATA_DIR=./data` in `.env`.

### Project layout

```
src/homegram/
├── bot.py              # wiring: DB lifecycle, auth guard, features, error handler
├── config.py           # settings from env
├── auth.py             # whitelist guard
├── strings.py          # user-facing texts
├── db/                 # SQLite connection, migrations, repositories
├── integrations/       # Home Assistant client
└── features/           # one module per feature (core, topics, shopping, tracker)
```

### Adding a feature

1. Create `src/homegram/features/<name>.py` with a `register(app)` function and a `FEATURE = Feature(...)`.
2. Add it to `FEATURES` in [`src/homegram/features/__init__.py`](src/homegram/features/__init__.py).
3. If it needs new tables, append a migration to [`src/homegram/db/migrations.py`](src/homegram/db/migrations.py) (never edit released ones).
4. Set `bindable=True` if it can be attached to a topic, then check `ctx.bindings.features_for(chat_id, thread_id)` in your handlers.
5. Set `requires_homeassistant=True` if it only makes sense with Home Assistant: it is then registered only when `HA_URL` and `HA_TOKEN` are set.

## License

[MIT](LICENSE)
