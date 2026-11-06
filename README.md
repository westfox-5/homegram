# 🏠 HomeGram

A small, modular Telegram bot for your home. Add it to your household group chat (forum **topics** supported) and use it for everyday home stuff.

**Features (v0.1)**

- 🛒 **Shared shopping list**: add items with `/spesa`, tick them off with inline buttons, clear completed ones.
- 📌 **Topic bindings**: attach a feature to a forum topic. In a topic bound to the shopping list, *any* message is added to the list.
- 💾 **Persistent state** in a single SQLite file: survives restarts and upgrades.
- 🏡 **Optional Home Assistant integration**: use a Home Assistant to-do entity as the shopping list.
- 🔒 **Whitelist** of users and chats.

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
| `/spesa latte, uova` | Add one or more items (commas, semicolons or new lines separate them). Without arguments it shows the list |
| `/lista` | Show the shopping list with ✅ buttons |

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

```bash
docker compose up -d --build
docker compose logs -f
```

### 4. Set up topics

In your group, open the topic you want to use for groceries (e.g. "🛒 Spesa") and send:

```
/bind spesa
```

From now on, every message written in that topic is added to the list (the bot reacts with 👍). Use `/lista` to see it and tick items off.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | Bot token from BotFather (required) |
| `ALLOWED_USER_IDS` | empty | Comma-separated Telegram user ids |
| `ALLOWED_CHAT_IDS` | empty | Comma-separated chat ids |
| `DATA_DIR` | `/data` | Folder holding `homegram.db` |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SHOPPING_BACKEND` | `sqlite` | `sqlite` (one list per chat) or `homeassistant` |
| `HA_URL` | — | e.g. `http://homeassistant.local:8123` |
| `HA_TOKEN` | — | Home Assistant long-lived access token |
| `HA_SHOPPING_ENTITY` | `todo.shopping_list` | To-do entity used by the `homeassistant` backend |

If both whitelists are empty, the bot ignores everyone except for `/id`.

## Home Assistant (optional)

1. In Home Assistant, open your profile → **Security** → **Long-lived access tokens** → create one.
2. Make sure you have a to-do list entity, e.g. the built-in **Shopping List** integration (`todo.shopping_list`).
3. Set `HA_URL`, `HA_TOKEN` and `SHOPPING_BACKEND=homeassistant`.

The list is then shared with the Home Assistant app and every chat. `/ping` reports whether Home Assistant is reachable.

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
└── features/           # one module per feature (core, topics, shopping)
```

### Adding a feature

1. Create `src/homegram/features/<name>.py` with a `register(app)` function and a `FEATURE = Feature(...)`.
2. Add it to `FEATURES` in [`src/homegram/features/__init__.py`](src/homegram/features/__init__.py).
3. If it needs new tables, append a migration to [`src/homegram/db/migrations.py`](src/homegram/db/migrations.py) (never edit released ones).
4. Set `bindable=True` if it can be attached to a topic, then check `ctx.bindings.features_for(chat_id, thread_id)` in your handlers.

## License

[MIT](LICENSE)
