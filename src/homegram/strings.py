"""User-facing texts (Italian). Kept in one place so they are easy to translate."""

BOT_NAME = "HomeGram"

START = (
    "🏠 <b>Ciao, sono {bot_name}!</b>\n"
    "Ti aiuto con le cose di casa. Ecco cosa so fare:\n\n"
    "{commands}"
)
HELP_TOPIC_FEATURES = "\n\n📌 In questo topic è attivo: <b>{features}</b>"
HELP_TOPIC_HINT = "\n<i>{hint}</i>"

PING_OK = "🏓 Pong!"
PING_DB = "🗄 Database: {status}"
PING_HA = "🏡 Home Assistant: {status}"
STATUS_OK = "ok"
STATUS_KO = "non raggiungibile"

ID_INFO = (
    "🪪 <b>Identificativi</b>\n"
    "Chat: <code>{chat_id}</code>\n"
    "Topic: <code>{thread_id}</code>\n"
    "Utente: <code>{user_id}</code>"
)

NOT_ALLOWED = "⛔️ Non sei autorizzato a usare questo bot."

BIND_USAGE = (
    "Uso: <code>/bind &lt;funzione&gt;</code> dentro il topic da collegare.\n"
    "Funzioni disponibili: {features}"
)
BIND_UNKNOWN = "Funzione sconosciuta: <b>{feature}</b>.\nFunzioni disponibili: {features}"
BIND_ONLY_GROUPS = "Questo comando funziona solo nei gruppi."
BIND_OK = "✅ Questo topic ora è collegato a <b>{feature}</b>."
BIND_ALREADY = "ℹ️ Questo topic è già collegato a <b>{feature}</b>."
UNBIND_USAGE = "Uso: <code>/unbind &lt;funzione&gt;</code> dentro il topic collegato."
UNBIND_OK = "🔌 Topic scollegato da <b>{feature}</b>."
UNBIND_MISSING = "ℹ️ Questo topic non è collegato a <b>{feature}</b>."
BINDINGS_EMPTY = "Nessun topic collegato in questa chat. Usa <code>/bind &lt;funzione&gt;</code>."
BINDINGS_HEADER = "📌 <b>Topic collegati</b>"
BINDINGS_GENERAL = "chat principale"
BINDINGS_TOPIC = "topic {thread_id}"

SHOP_TITLE = "🛒 <b>Lista della spesa</b> ({count})"
SHOP_EMPTY = "🛒 La lista della spesa è vuota 🎉"
SHOP_MORE = "<i>…e altri {count}</i>"
SHOP_ADDED = "🛒 Aggiunto: {items}"
SHOP_BTN_REFRESH = "🔄 Aggiorna"
SHOP_BTN_CLEAR = "🧹 Pulisci completati"
SHOP_DONE = "✅ Fatto!"
SHOP_NOT_FOUND = "Elemento non trovato (forse è già stato spuntato)."
SHOP_CLEARED = "🧹 Rimossi {count} completati"
SHOP_CLEARED_UNKNOWN = "🧹 Completati rimossi"
SHOP_TOPIC_HINT = "Scrivi qui qualsiasi cosa e la aggiungo alla lista. /lista per vederla."

HA_UNAVAILABLE = "⚠️ Home Assistant non è raggiungibile, riprova tra poco."
GENERIC_ERROR = "⚠️ Qualcosa è andato storto. Riprova."
