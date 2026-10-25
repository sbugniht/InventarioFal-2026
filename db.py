"""Database SQLite dell'inventario (un file: inventario.db).
Al primo avvio importa articoli e zone dalla cartella dati/ e crea l'utente admin."""
import datetime
import hashlib
import json
import os
import secrets
import sqlite3
import threading

from config import BASE_DIR, CONFIG
from misure_auto import misure_da_descrizione

PERCORSO_DB = os.path.join(BASE_DIR, CONFIG.get("database", "inventario.db"))
MISURE = ["spessore", "larghezza", "lunghezza", "trasversali"]
CAMPI_RIGA = ["pezzi", *MISURE]

SCHEMA = """
CREATE TABLE IF NOT EXISTS utenti (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE COLLATE NOCASE,
    ruolo TEXT NOT NULL DEFAULT 'operatore',     -- operatore | admin
    pin_hash TEXT NOT NULL,
    attivo INTEGER NOT NULL DEFAULT 1,
    creato TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessioni (
    token TEXT PRIMARY KEY,
    utente_id INTEGER NOT NULL REFERENCES utenti(id),
    creata TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articoli (
    id INTEGER PRIMARY KEY,
    codice TEXT NOT NULL UNIQUE COLLATE NOCASE,
    descrizione TEXT NOT NULL DEFAULT '',
    unita TEXT NOT NULL DEFAULT '',
    spessore REAL, larghezza REAL, lunghezza REAL, trasversali REAL,
    misure_auto INTEGER NOT NULL DEFAULT 0,     -- 1 = misure lette dalla descrizione, da verificare
    parlato TEXT NOT NULL DEFAULT '{}',         -- unità in cui si dicono i numeri, es. {"larghezza": "mm"}
    sinonimi TEXT NOT NULL DEFAULT '',          -- nomi usati a voce, separati da |
    attivo INTEGER NOT NULL DEFAULT 1,
    modificato TEXT
);
CREATE TABLE IF NOT EXISTS zone (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE COLLATE NOCASE,
    attiva INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS inventari (
    id INTEGER PRIMARY KEY,
    chiuso_il TEXT NOT NULL,
    chiuso_da INTEGER REFERENCES utenti(id)
);
CREATE TABLE IF NOT EXISTS righe (
    id TEXT PRIMARY KEY,                        -- generato dal tablet: un reinvio non crea doppioni
    utente_id INTEGER NOT NULL REFERENCES utenti(id),
    articolo_id INTEGER NOT NULL REFERENCES articoli(id),
    pezzi REAL, spessore REAL, larghezza REAL, lunghezza REAL, trasversali REAL,
    note TEXT NOT NULL DEFAULT '',
    zona_id INTEGER REFERENCES zone(id),
    trascrizione TEXT,                          -- testo di Whisper (cancellato dopo N giorni)
    metodo TEXT NOT NULL DEFAULT 'manuale',     -- manuale | voce:regole | voce:llm | voce:scelta
    offline INTEGER NOT NULL DEFAULT 0,         -- 1 = salvata senza rete e inviata dopo
    creata TEXT NOT NULL,
    modificata TEXT,
    inventario_id INTEGER REFERENCES inventari(id)   -- NULL = inventario in corso
);
CREATE INDEX IF NOT EXISTS righe_correnti ON righe(inventario_id, creata);
CREATE TABLE IF NOT EXISTS notifiche (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,                         -- doppione | articolo_mancante
    riga_id TEXT REFERENCES righe(id),
    utente_id INTEGER REFERENCES utenti(id),
    testo TEXT NOT NULL,
    creata TEXT NOT NULL,
    gestita_il TEXT,
    gestita_da INTEGER REFERENCES utenti(id)
);
"""

_lock = threading.RLock()
_conn = None


def adesso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def connessione() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(PERCORSO_DB, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(SCHEMA)
    return _conn


def tutti(sql, params=()):
    with _lock:
        return [dict(r) for r in connessione().execute(sql, params).fetchall()]


def uno(sql, params=()):
    with _lock:
        r = connessione().execute(sql, params).fetchone()
        return dict(r) if r else None


def esegui(sql, params=()):
    with _lock:
        return connessione().execute(sql, params)


class transazione:
    """with transazione(): ... -> tutto o niente."""
    def __enter__(self):
        _lock.acquire()
        connessione().execute("BEGIN")

    def __exit__(self, tipo, *_):
        connessione().execute("ROLLBACK" if tipo else "COMMIT")
        _lock.release()


# --- PIN e password -----------------------------------------------------------
def hash_pin(pin: str) -> str:
    sale = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(sale), 200_000).hex()
    return f"{sale}${h}"


def verifica_pin(pin: str, salvato: str) -> bool:
    sale, h = salvato.split("$", 1)
    prova = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(sale), 200_000).hex()
    return secrets.compare_digest(prova, h)


# --- Primo avvio ---------------------------------------------------------------
def importa_articoli():
    """Importa dati/articoli.csv (export di Altervista) con le misure di misure_articoli.csv
    e quelle lette dalle descrizioni. Solo se la tabella è vuota."""
    from catalogo import Catalogo
    cat = Catalogo()
    with transazione():
        for a in cat.articoli:
            misure = {c: a[k] for c, k in
                      [("spessore", "thickness"), ("larghezza", "width"), ("lunghezza", "length"),
                       ("trasversali", "transversal")] if a[k] is not None}
            auto = 0
            if not misure:
                misure = misure_da_descrizione(a["description"], a["unit"])
                auto = 1 if misure else 0
            parlato, sinonimi = {}, []
            # misure_articoli.csv: dalla famiglia più generica all'articolo, il più specifico vince
            for voce in reversed(cat.voci_misure(a["code_search"])):
                if voce["fisse"]:
                    misure.update(voce["fisse"])
                    auto = 0
                parlato.update(voce["parlato"])
                sinonimi += voce["sinonimi"]
            connessione().execute(
                "INSERT OR IGNORE INTO articoli (id, codice, descrizione, unita, spessore, larghezza, lunghezza, "
                "trasversali, misure_auto, parlato, sinonimi, modificato) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (a["id"], a["code_search"], a["description"], a["unit"], misure.get("spessore"),
                 misure.get("larghezza"), misure.get("lunghezza"), misure.get("trasversali"), auto,
                 json.dumps(parlato), "|".join(sinonimi), adesso()))
        for nome in cat.zone:
            connessione().execute("INSERT OR IGNORE INTO zone (nome) VALUES (?)", (nome,))
    return len(cat.articoli), cat.file_articoli


def inizializza():
    connessione()
    messaggi = []
    if not uno("SELECT id FROM articoli LIMIT 1"):
        n, file = importa_articoli()
        messaggi.append(f"[📦] Importati {n} articoli da dati/{file}")
    if not uno("SELECT id FROM utenti WHERE ruolo = 'admin' AND attivo = 1"):
        password = secrets.token_urlsafe(9)
        esegui("INSERT OR REPLACE INTO utenti (id, nome, ruolo, pin_hash, creato) "
               "VALUES ((SELECT id FROM utenti WHERE nome = 'admin'), 'admin', 'admin', ?, ?)",
               (hash_pin(password), adesso()))
        messaggi.append(f"[🔑] Creato l'utente admin. Password: {password}  (cambiala dalla pagina admin)")
    return messaggi


if __name__ == "__main__":
    # python db.py reset-admin  -> nuova password per l'admin
    import sys
    if sys.argv[1:] == ["reset-admin"]:
        connessione()
        password = secrets.token_urlsafe(9)
        esegui("UPDATE utenti SET pin_hash = ?, attivo = 1 WHERE nome = 'admin'", (hash_pin(password),))
        print(f"Nuova password admin: {password}")
    else:
        print("\n".join(inizializza()) or "Database già pronto.")
