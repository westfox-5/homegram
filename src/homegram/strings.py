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

BIND_UNKNOWN = "Funzione sconosciuta: <b>{feature}</b>.\nFunzioni disponibili: {features}"
BIND_ASK = "🔗 Quale funzione collego a questo topic?"
UNBIND_ASK = "🔌 Quale funzione scollego da questo topic?"
UNBIND_NONE = "ℹ️ Questo topic non è collegato a nessuna funzione."
BIND_ONLY_GROUPS = "Questo comando funziona solo nei gruppi."
BIND_OK = "✅ Questo topic ora è collegato a <b>{feature}</b>."
BIND_ALREADY = "ℹ️ Questo topic è già collegato a <b>{feature}</b>."
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
SHOP_TOPIC_HINT = "Scrivi qui qualsiasi cosa e la aggiungo alla lista. /spesa per vederla."
SHOP_ASK_ADD = "🛒 Cosa aggiungo alla lista? Separa le voci con virgole o a capo."

HA_UNAVAILABLE = "⚠️ Home Assistant non è raggiungibile, riprova tra poco."
GENERIC_ERROR = "⚠️ Qualcosa è andato storto. Riprova."

PROMPT_BTN_CANCEL = "✖️ Annulla"
PROMPT_CANCELLED = "↩️ Annullato."
PROMPT_NOTHING = "Nessuna domanda in corso."
PROMPT_EXPIRED = "⌛ Domanda scaduta: rilancia il comando."

TRACKER_TITLE = "📈 <b>Tracker prezzi</b> ({count})"
TRACKER_EMPTY = "📈 Nessun prodotto tracciato.\nAggiungine uno con /tracker_aggiungi."
TRACKER_FOOTER = (
    "<i>In grassetto il prezzo migliore tra i negozi con disponibilità. "
    "Home Assistant aggiorna ogni ~10 min.</i>"
)
TRACKER_NO_PRICE = "—"
TRACKER_STOCK_UNKNOWN = "❔ n.d."
TRACKER_STOCK_OUT = "❌ esaurito"
TRACKER_BTN_REFRESH = "🔄 Aggiorna"
TRACKER_BTN_CONFIRM = "🗑 Sì, elimina"
TRACKER_BTN_CANCEL = "↩️ Annulla"
TRACKER_USAGE = (
    "Uso: <code>/tracker_aggiungi &lt;nome prodotto&gt; &lt;link&gt;</code>\n"
    "Con il nome di un prodotto già tracciato aggiungi un altro negozio.\n"
    "Negozi supportati: {shops}"
)
TRACKER_ASK_START = (
    "📈 Scegli un prodotto tracciato per aggiungere un negozio, oppure mandami il link "
    "di un nuovo prodotto.\nNegozi supportati: {shops}"
)
TRACKER_ASK_START_EMPTY = (
    "📈 Mandami il link del prodotto da tracciare.\nNegozi supportati: {shops}"
)
TRACKER_ASK_LINK_NEW = "🔗 Mandami il link di <b>{product}</b>.\nNegozi supportati: {shops}"
TRACKER_ASK_LINK_EXISTING = (
    "🔗 Mandami il link di un altro negozio per <b>{product}</b>.\nNegozi supportati: {shops}"
)
TRACKER_ASK_LINK_AGAIN = "⚠️ Non vedo un link: mandami il link del prodotto (https://…)."
TRACKER_ASK_NAME = "🏷 Link {shop} ok. Come chiamo questo prodotto?"
TRACKER_ASK_NAME_EXISTING = "\nOppure aggiungilo a un prodotto già tracciato:"
TRACKER_ASK_REMOVE = "🗑 Quale prodotto smetto di tracciare?"
TRACKER_RETRY = "\n<i>Riprova o premi Annulla.</i>"
TRACKER_REMOVE_USAGE = (
    "Uso: <code>/tracker_rimuovi &lt;nome prodotto&gt;</code>\n"
    "Per eliminare un solo negozio usa i pulsanti 🗑 di /tracker."
)
TRACKER_ADDED_PRODUCT = "✅ Ora traccio <b>{product}</b> su {shop}."
TRACKER_ADDED_LINK = "✅ Aggiunto {shop} a <b>{product}</b>."
TRACKER_NO_VALUE_YET = (
    "<i>Prezzo non ancora letto: se resta vuoto il negozio potrebbe bloccare lo scraper "
    "o il link non è una pagina prodotto.</i>"
)
TRACKER_NOT_FOUND = "Nessun prodotto tracciato si chiama <b>{product}</b>. Vedi /tracker."
TRACKER_CONFIRM_PRODUCT = (
    "Smetto di tracciare <b>{product}</b>? Elimino {count} scraper da Home Assistant."
)
TRACKER_CONFIRM_LINK = "Confermi l'eliminazione?"
TRACKER_CANCELLED = "↩️ Annullato."
TRACKER_REMOVED_PRODUCT = "🗑 Non traccio più <b>{product}</b>."
TRACKER_REMOVED_TOAST = "🗑 Eliminato"
TRACKER_GONE = "Questo scraper non esiste più."
TRACKER_ERR_SHOP = (
    "⚠️ Link non supportato: serve la pagina di un prodotto.\nNegozi supportati: {shops}"
)
TRACKER_ERR_SHORT_LINK = (
    "⚠️ Non riesco ad aprire il link breve. Riprova o manda il link completo del prodotto."
)
TRACKER_ERR_LONG_NAME = "⚠️ Nome troppo lungo (max {max} caratteri)."
TRACKER_ERR_DUPLICATE_URL = "ℹ️ Questo link è già tracciato in <b>{product}</b>."
TRACKER_ERR_DUPLICATE_SHOP = (
    "ℹ️ <b>{product}</b> ha già un link {shop}. Eliminalo da /tracker per sostituirlo."
)
TRACKER_ERR_FLOW = (
    "⚠️ Home Assistant non ha creato lo scraper (<code>{errors}</code>). "
    "Controlla che il link si apra."
)
TRACKER_ERR_FORBIDDEN = (
    "⛔️ Home Assistant ha rifiutato la richiesta: il token in <code>HA_TOKEN</code> "
    "deve essere di un utente <b>amministratore</b> per gestire gli scraper."
)

TRACKER_NOTIFY_ON = "🔔 <b>Notifiche tracker attive</b>"
TRACKER_NOTIFY_OFF = "🔕 <b>Notifiche tracker disattivate</b>"
TRACKER_NOTIFY_HELP = (
    "<i>Arrivano tramite l'app Home Assistant quando cambia un prezzo o un prodotto "
    "torna disponibile / si esaurisce. Tocca i pulsanti per cambiare.</i>"
)
TRACKER_NOTIFY_DEVICES = "📱 <b>Dispositivi</b>"
TRACKER_NOTIFY_NO_DEVICES = "<i>Nessun dispositivo con l'app Home Assistant.</i>"
TRACKER_NOTIFY_PRODUCTS = "📦 <b>Prodotti</b>"
TRACKER_NOTIFY_NO_PRODUCTS = "<i>Nessun prodotto tracciato.</i>"
TRACKER_BTN_NOTIFY_ON = "🔔 Attiva notifiche"
TRACKER_BTN_NOTIFY_OFF = "🔕 Disattiva notifiche"
TRACKER_ERR_NO_DEVICES = "📱 Scegli prima almeno un dispositivo."
TRACKER_ERR_NO_PRODUCTS = "📦 Traccia prima almeno un prodotto con /tracker_aggiungi."
TRACKER_ERR_NOTIFY_DISABLED = (
    "🔕 Notifiche non configurabili: <code>HA_TRACKER_AUTOMATION</code> è vuoto."
)
