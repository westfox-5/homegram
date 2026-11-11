# 🏠 HomeGram

A small, modular Telegram bot for your home. Add it to your household group chat (forum **topics** supported) and use it for everyday home stuff.

**Features**

- 🛒 **Shared shopping list**: add items with `/spesa_aggiungi`, see the list with `/spesa`, tick them off with inline buttons, clear completed ones.
- 📌 **Topic bindings**: attach a feature to a forum topic. In a topic bound to the shopping list, *any* message is added to the list.
- 💾 **Persistent state** in a single SQLite file: survives restarts and upgrades.
- 🏡 **Optional Home Assistant integration**: use a Home Assistant to-do entity as the shopping list.
- 📈 **Price tracker** *(Home Assistant only)*: track prices and stock of products across shops with `/tracker_aggiungi`; the bot creates the scrapers in Home Assistant for you and posts price and stock changes to a topic.
- 🎬 **Scenes** *(Home Assistant only)*: `/scene` runs your Home Assistant scenes and scripts from buttons.
- ⚡️ **Energy** *(Home Assistant only)*: `/energia` shows solar, battery, house and grid; a daily report and solar surplus alerts go to a topic.
- 🤖 **Robot vacuum** *(Home Assistant only)*: notifications when it starts, gets stuck or a part wears out.
- 🗑 **Waste collection** *(Home Assistant only)*: `/bidoni` lists the next pickups; a reminder with "Fatto" / "Non serve" buttons the evening before.
- 🔒 **Whitelist** of users and chats.

Commands are grouped by feature: each feature has a main command (`/spesa`, `/tracker`) and sub-commands prefixed with its name (`/spesa_aggiungi`, `/tracker_aggiungi`, …). The old `/lista` and `/spesa <items>` still work as aliases.

The bot's messages are in Italian (all texts live in [`src/homegram/strings.py`](src/homegram/strings.py), so you can translate them).

## Commands

| Command | Description |
| --- | --- |
| `/help` | List commands and the features active in the current topic |
| `/ping` | Check that the bot, the database and Home Assistant (if configured) are working |
| `/id` | Show chat, topic and user ids (available to everyone, useful for setup) |
| `/annulla` | Cancel the pending follow-up question |
| `/bind [feature]` | Attach a feature to the current topic (e.g. `/bind spesa`; without it, pick from buttons) |
| `/unbind [feature]` | Detach a feature from the current topic |
| `/bindings` | List the topic bindings of this chat |
| `/spesa` | Show the shopping list with ✅ buttons |
| `/spesa_aggiungi [latte, uova]` | Add one or more items (commas, semicolons or new lines separate them) |
| `/tracker` | Prices and stock of the tracked products, with 🗑 buttons to remove a shop *(Home Assistant only)* |
| `/tracker_aggiungi [product] [link]` | Track a product page. With the name of a product already tracked, adds another shop *(Home Assistant only)* |
| `/tracker_rimuovi [product]` | Stop tracking a product and delete all its scrapers *(Home Assistant only)* |
| `/tracker_notifiche` | Where the tracker notifications go, and which products to mute *(Home Assistant only)* |
| `/scene` | Buttons to run Home Assistant scenes and scripts *(Home Assistant only)* |
| `/energia` | Solar, battery, house and grid now and today, tomorrow's forecast *(Home Assistant, `ENERGY_*` set)* |
| `/bidoni` | Next waste pickups *(Home Assistant, waste_collection_schedule)* |

Arguments in brackets can be left out: the bot then asks for them. For example `/tracker_aggiungi` alone shows the tracked products as buttons (to add another shop to one of them) and waits for the link of a new product, then for its name. The next text message you send in the same chat or topic is the answer; any other command, the ✖️ button or `/annulla` cancel the question, and it expires after 10 minutes.

## Quick start

### 1. Create the bot

1. Talk to [@BotFather](https://t.me/BotFather), run `/newbot` and copy the token.
2. Run `/setprivacy` → choose your bot → **Disable**. This lets the bot read normal messages in a bound topic and the answers to its questions (otherwise it only sees commands and replies to its own messages). Telegram applies the change to a group only after you remove the bot and add it again; making the bot an admin of the group works too. The bot logs a warning at startup while privacy mode is on, and its questions then ask you to reply to them.
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
| `HA_TRACKER_AUTOMATION` | `tracker_notifica` | Old Home Assistant automation of the tracker notifications: its muted products are imported once. The bot does not change it |
| `HA_SCENES` | auto | Comma-separated scenes/scripts for `/scene`. Empty: every `scene.*` and every script without input fields |
| `HA_VACUUM` | — | Robot vacuum entity; enables the `pulizie` notifications |
| `HA_VACUUM_BATTERY` / `HA_VACUUM_ERROR` | auto | Battery sensor and error sensor (its `description` attribute) of the robot. Empty: found on the robot's device |
| `HA_VACUUM_PARTS` | auto | Comma-separated lifespan sensors (%). Empty: every `%` sensor of the robot's device |
| `VACUUM_PARTS_THRESHOLD` | `10` | Notify when a part drops below this % |
| `HA_WASTE_SENSORS` | auto | Comma-separated waste_collection_schedule sensors. Empty: all of them |
| `WASTE_REMINDER_TIME` / `WASTE_REPEAT_TIME` | `19:30` / `21:30` | Reminder the evening before a pickup, and its repetition if nobody answered (empty: no repetition) |
| `ENERGY_SOLAR_POWER`, `ENERGY_LOAD_POWER`, `ENERGY_GRID_POWER`, `ENERGY_BATTERY_POWER`, `ENERGY_BATTERY_SOC` | — | Power sensors (W or kW) and battery %. Grid: > 0 import, < 0 export. Battery: > 0 charging |
| `ENERGY_SOLAR_TODAY`, `ENERGY_LOAD_TODAY`, `ENERGY_IMPORT_TODAY`, `ENERGY_EXPORT_TODAY` | — | Today's totals (kWh) |
| `ENERGY_FORECAST_TODAY`, `ENERGY_FORECAST_TOMORROW`, `ENERGY_PEAK_TOMORROW` | — | Solar forecast (e.g. Forecast.Solar): kWh and the time of tomorrow's peak |
| `ENERGY_SURPLUS_KW` | `1` | Surplus alert when exporting more than this for 10 minutes (once a day) |
| `ENERGY_REPORT_TIME` | `21:00` | Daily energy report (empty: off) |
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
- **Notifications** go to the topics bound with `/bind tracker` (`/unbind tracker` to stop): a price change of at least 5 € (🔴 up, 🟢 down), or a product going in or out of stock (not every piece sold). Each one has a button to mute that product; `/tracker_notifiche` shows where they go and mutes or unmutes products. Muted products are stored in the bot's database (imported once from the old `tracker_notifica` automation, see `HA_TRACKER_AUTOMATION`).

## Notifications from Home Assistant

Some features post Home Assistant events to a topic. Bind each one to the topic where you want it, e.g. `/bind tracker` in a "Tracker" topic and `/bind pulizie`, `/bind energia`, `/bind bidoni` in a "Casa" topic. A feature that is not bound anywhere sends nothing.

| Feature | Sends |
| --- | --- |
| `tracker` | Price (±5 €) and stock changes of the tracked products |
| `pulizie` | The robot vacuum starts cleaning (once, not when it goes back to wash the mop), is stuck or in error for a minute, a part drops below `VACUUM_PARTS_THRESHOLD` |
| `energia` | Solar surplus (export above `ENERGY_SURPLUS_KW` for 10 minutes, once a day), daily report at `ENERGY_REPORT_TIME` |
| `bidoni` | At `WASTE_REMINDER_TIME`, if something is collected tomorrow: what to put out, with ✅ Fatto / 👌 Non serve buttons. Repeated at `WASTE_REPEAT_TIME` if nobody tapped them |
| `scene` | Nothing: bind it to the topic where you use `/scene` |

How it works: the bot keeps a connection to the Home Assistant WebSocket API and subscribes to *triggers* (state, numeric state, time of day), the same ones you would use in an automation. Home Assistant evaluates them, including durations and times in its own time zone, and tells the bot when they fire. Events that fire while the bot is offline are lost. If you used Home Assistant automations for the same notifications, turn them off to avoid duplicates.

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
├── prompts.py          # follow-up questions for missing command arguments
├── notify.py           # post a feature's notifications to its bound topics
├── db/                 # SQLite connection, migrations, repositories
├── integrations/       # Home Assistant REST client and WebSocket events
└── features/           # one module per feature (core, topics, shopping, tracker, scene,
                        # energia, pulizie, bidoni)
```

### Adding a feature

1. Create `src/homegram/features/<name>.py` with a `register(app)` function and a `FEATURE = Feature(...)`.
2. Add it to `FEATURES` in [`src/homegram/features/__init__.py`](src/homegram/features/__init__.py).
3. If it needs new tables, append a migration to [`src/homegram/db/migrations.py`](src/homegram/db/migrations.py) (never edit released ones).
4. Set `bindable=True` if it can be attached to a topic, then check `ctx.bindings.features_for(chat_id, thread_id)` in your handlers.
5. Set `requires_homeassistant=True` if it only makes sense with Home Assistant: it is then registered only when `HA_URL` and `HA_TOKEN` are set. Use `available=` for extra conditions on the settings (e.g. an entity must be configured).
6. To notify from Home Assistant events, set `start=` to a coroutine that registers triggers with `ctx.events.subscribe(name, trigger, callback)` (inside an `ctx.events.on_connect` hook if they depend on HA data) and posts with `notify.to_feature(...)`.
7. To ask for missing command arguments, use `prompts.ask(...)` and register the answer handler with `prompts.on_answer(...)`.

## License

[MIT](LICENSE)
