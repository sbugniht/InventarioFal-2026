"""Pagine e API dell'inventario: accesso con nome + PIN, righe, admin, export CSV."""
import asyncio
import csv
import datetime
import io
import json
import os
import secrets
import shutil
import tempfile
import time

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import db
import inventario
import ricerca
import trascrizione
from config import BASE_DIR, CONFIG

STATIC = os.path.join(BASE_DIR, "static")
COOKIE = "sessione"
MINUTI_DOPPIONE = CONFIG.get("minuti_doppione", 10)

_indice = None
_tentativi = {}  # utente_id -> (errori, bloccato_fino_a)


def indice() -> ricerca.Indice:
    global _indice
    if _indice is None:
        _indice = ricerca.Indice(articoli_inventariabili())
    return _indice


def ricostruisci_indice():
    global _indice
    _indice = None


def articoli_inventariabili():
    escluse = [u for u, r in inventario.REGOLE["unita"].items() if r.get("inventariabile") is False]
    segnaposto = ",".join("?" * len(escluse)) or "''"
    return db.tutti(f"SELECT * FROM articoli WHERE attivo = 1 AND unita NOT IN ({segnaposto}) ORDER BY codice",
                    escluse)


# --- Risposte e controlli -------------------------------------------------------
class Errore(Exception):
    def __init__(self, stato, messaggio):
        self.stato, self.messaggio = stato, messaggio


def utente(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    return db.uno("SELECT u.id, u.nome, u.ruolo FROM sessioni s JOIN utenti u ON u.id = s.utente_id "
                  "WHERE s.token = ? AND u.attivo = 1", (token,))


def api(ruolo=None):
    """Decoratore: controlla l'accesso e trasforma gli Errore in risposte JSON."""
    def decora(funzione):
        async def gestore(request: Request):
            u = utente(request)
            if ruolo and not u:
                return JSONResponse({"errore": "Accesso richiesto"}, status_code=401)
            if ruolo == "admin" and u["ruolo"] != "admin":
                return JSONResponse({"errore": "Solo per l'admin"}, status_code=403)
            try:
                return await funzione(request, u)
            except Errore as e:
                return JSONResponse({"errore": e.messaggio}, status_code=e.stato)
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                return JSONResponse({"errore": f"Dati non validi: {e}"}, status_code=400)
        return gestore
    return decora


def numero(valore, campo):
    if valore is None or valore == "":
        return None
    try:
        n = float(str(valore).replace(",", "."))
    except ValueError:
        raise Errore(400, f"{campo}: non è un numero")
    if n < 0:
        raise Errore(400, f"{campo}: non può essere negativo")
    return n


# --- Pagine ---------------------------------------------------------------------
def _html(nome):
    return FileResponse(os.path.join(STATIC, f"{nome}.html"), headers={"Cache-Control": "no-cache"})


async def pagina_home(request: Request):
    u = utente(request)
    if not u:
        return RedirectResponse("/login")
    return RedirectResponse("/admin" if u["ruolo"] == "admin" else "/operatore")


async def pagina_login(request: Request):
    return _html("login")


async def pagina_operatore(request: Request):
    # Senza sessione valida la pagina si apre lo stesso (anche dalla cache offline):
    # è il JavaScript a rimandare al login quando il server risponde 401
    return _html("operatore")


async def pagina_admin(request: Request):
    u = utente(request)
    if not u:
        return RedirectResponse("/login")
    if u["ruolo"] != "admin":
        return RedirectResponse("/operatore")
    return _html("admin")


FILE_STATICI = {"stile.css", "comune.js", "operatore.js", "admin.js", "sw.js"}


async def file_statico(request: Request):
    nome = request.path_params.get("nome", "sw.js")
    if nome not in FILE_STATICI:
        return Response(status_code=404)
    # sw.js è servito dalla radice: così il service worker vale per tutto il sito
    return FileResponse(os.path.join(STATIC, nome), headers={"Cache-Control": "no-cache"})


# --- Accesso --------------------------------------------------------------------
@api()
async def utenti_accesso(request, u):
    return JSONResponse(db.tutti("SELECT id, nome, ruolo FROM utenti WHERE attivo = 1 ORDER BY ruolo DESC, nome"))


@api()
async def accesso(request, u):
    dati = await request.json()
    utente_id, pin = int(dati["utente_id"]), str(dati["pin"])
    errori, bloccato = _tentativi.get(utente_id, (0, 0))
    if bloccato > time.time():
        raise Errore(429, f"Troppi tentativi: riprova tra {int(bloccato - time.time()) + 1} secondi")
    riga = db.uno("SELECT * FROM utenti WHERE id = ? AND attivo = 1", (utente_id,))
    if not riga or not db.verifica_pin(pin, riga["pin_hash"]):
        errori += 1
        _tentativi[utente_id] = (errori, time.time() + 60 if errori >= 5 else 0)
        raise Errore(401, "PIN sbagliato")
    _tentativi.pop(utente_id, None)
    token = secrets.token_urlsafe(32)
    db.esegui("INSERT INTO sessioni (token, utente_id, creata) VALUES (?, ?, ?)", (token, utente_id, db.adesso()))
    risposta = JSONResponse({"id": riga["id"], "nome": riga["nome"], "ruolo": riga["ruolo"]})
    risposta.set_cookie(COOKIE, token, max_age=60 * 60 * 24 * 30, httponly=True, secure=True, samesite="strict")
    return risposta


@api()
async def uscita(request, u):
    db.esegui("DELETE FROM sessioni WHERE token = ?", (request.cookies.get(COOKIE, ""),))
    risposta = JSONResponse({"ok": True})
    risposta.delete_cookie(COOKIE)
    return risposta


@api("operatore")
async def chi_sono(request, u):
    return JSONResponse(u)


# --- Catalogo e zone (copiati sul tablet per lavorare anche senza rete) --------
@api("operatore")
async def catalogo(request, u):
    articoli = [{k: a[k] for k in ("id", "codice", "descrizione", "unita", "spessore", "larghezza", "lunghezza",
                                   "trasversali", "misure_auto")} for a in articoli_inventariabili()]
    zone = db.tutti("SELECT id, nome FROM zone WHERE attiva = 1 ORDER BY nome")
    return JSONResponse({"articoli": articoli, "zone": zone, "regole": inventario.REGOLE})


# --- Voce -----------------------------------------------------------------------
CAMPIONI = os.path.join(BASE_DIR, "campioni")


def _tieni_campione(u) -> bool:
    """Solo per l'utente di prova: l'audio resta in campioni/ per confrontare i modelli."""
    nome = CONFIG.get("utente_campioni")
    return bool(nome) and u["nome"].lower() == nome.lower()


@api("operatore")
async def voce(request, u):
    form = await request.form()
    audio = form["audio"]
    estensione = os.path.splitext(audio.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=estensione, delete=False) as f:
        f.write(await audio.read())
        percorso = f.name
    campione, testo, risultato = None, "", None
    try:
        testo = await asyncio.to_thread(trascrizione.trascrivi, percorso)
    finally:
        if _tieni_campione(u):
            os.makedirs(CAMPIONI, exist_ok=True)
            campione = os.path.join(CAMPIONI, f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}")
            shutil.move(percorso, campione + estensione)
        else:
            os.remove(percorso)  # l'audio non viene mai conservato (tranne per l'utente di prova)
    try:
        if not testo:
            raise Errore(422, "Non ho sentito niente, riprova.")
        zone = db.tutti("SELECT id, nome FROM zone WHERE attiva = 1")
        risultato = await asyncio.to_thread(inventario.analizza, testo, indice(), zone)
        return JSONResponse(risultato)
    finally:
        if campione:
            # Risposta data al tablet: la riga salvata dopo (stessa trascrizione) è quella giusta
            with open(campione + ".json", "w", encoding="utf-8") as f:
                json.dump({"creato": db.adesso(), "utente": u["nome"], "audio": os.path.basename(campione) + estensione,
                           "whisper": CONFIG["whisper_modello"], "llm": CONFIG["llm_modello"] if CONFIG["llm_attivo"]
                           else None, "testo": testo, "risultato": risultato}, f, ensure_ascii=False, indent=1)


@api("operatore")
async def applica(request, u):
    """Il tablet ha cambiato articolo: ricalcola i campi con le misure fisse del nuovo articolo."""
    dati = await request.json()
    articolo = db.uno("SELECT * FROM articoli WHERE id = ?", (int(dati["articolo_id"]),))
    if not articolo:
        raise Errore(404, "Articolo non trovato")
    detti = {c: tuple(v) for c, v in (dati.get("detti") or {}).items() if c in inventario.CAMPI}
    return JSONResponse(inventario.applica(articolo, detti))


# --- Righe dell'inventario -------------------------------------------------------
def _valori_riga(dati):
    articolo = db.uno("SELECT id FROM articoli WHERE id = ?", (int(dati["articolo_id"]),))
    if not articolo:
        raise Errore(400, "Articolo inesistente")
    zona_id = dati.get("zona_id") or None
    if zona_id and not db.uno("SELECT id FROM zone WHERE id = ?", (int(zona_id),)):
        raise Errore(400, "Zona inesistente")
    valori = {c: numero(dati.get(c), c) for c in inventario.CAMPI}
    valori.update(articolo_id=articolo["id"], zona_id=int(zona_id) if zona_id else None,
                  note=str(dati.get("note") or "")[:500])
    return valori


def _controlla_doppione(riga_id, valori, u):
    """Stesso articolo, zona e numeri salvato da poco (da chiunque): avviso all'admin, la riga resta."""
    limite = (datetime.datetime.now() - datetime.timedelta(minutes=MINUTI_DOPPIONE)).isoformat(timespec="seconds")
    simile = db.uno(
        "SELECT r.id, r.creata, u.nome FROM righe r JOIN utenti u ON u.id = r.utente_id "
        "WHERE r.id != ? AND r.inventario_id IS NULL AND r.articolo_id = ? AND r.zona_id IS ? AND r.creata >= ? "
        "AND r.pezzi IS ? AND r.spessore IS ? AND r.larghezza IS ? AND r.lunghezza IS ? AND r.trasversali IS ? "
        "ORDER BY r.creata DESC",
        (riga_id, valori["articolo_id"], valori["zona_id"], limite, *[valori[c] for c in inventario.CAMPI]))
    if simile:
        articolo = db.uno("SELECT codice, descrizione FROM articoli WHERE id = ?", (valori["articolo_id"],))
        db.esegui("INSERT INTO notifiche (tipo, riga_id, utente_id, testo, creata) VALUES ('doppione', ?, ?, ?, ?)",
                  (riga_id, u["id"],
                   f"Possibile doppione: {articolo['codice']} {articolo['descrizione']} salvato da {u['nome']} "
                   f"uguale a una riga di {simile['nome']} delle {simile['creata'][11:16]}", db.adesso()))


@api("operatore")
async def salva_riga(request, u):
    dati = await request.json()
    riga_id = str(dati["id"])[:64]
    esistente = db.uno("SELECT utente_id FROM righe WHERE id = ?", (riga_id,))
    if esistente:
        # Reinvio dalla coda offline: è già salvata
        return JSONResponse({"ok": True, "id": riga_id, "gia_salvata": True})
    valori = _valori_riga(dati)
    db.esegui(
        "INSERT INTO righe (id, utente_id, articolo_id, pezzi, spessore, larghezza, lunghezza, trasversali, note, "
        "zona_id, trascrizione, metodo, offline, creata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (riga_id, u["id"], valori["articolo_id"], *[valori[c] for c in inventario.CAMPI], valori["note"],
         valori["zona_id"], (dati.get("trascrizione") or None), str(dati.get("metodo") or "manuale")[:20],
         1 if dati.get("offline") else 0, str(dati.get("creata") or db.adesso())[:19]))
    _controlla_doppione(riga_id, valori, u)
    return JSONResponse({"ok": True, "id": riga_id})


def _riga_modificabile(riga_id, u):
    riga = db.uno("SELECT * FROM righe WHERE id = ? AND inventario_id IS NULL", (riga_id,))
    if not riga or (u["ruolo"] != "admin" and riga["utente_id"] != u["id"]):
        raise Errore(404, "Riga non trovata")  # le righe degli altri non si vedono nemmeno
    return riga


@api("operatore")
async def modifica_riga(request, u):
    riga_id = request.path_params["id"]
    _riga_modificabile(riga_id, u)
    if request.method == "DELETE":
        db.esegui("DELETE FROM notifiche WHERE riga_id = ?", (riga_id,))
        db.esegui("DELETE FROM righe WHERE id = ?", (riga_id,))
        return JSONResponse({"ok": True})
    valori = _valori_riga(await request.json())
    db.esegui("UPDATE righe SET articolo_id=?, pezzi=?, spessore=?, larghezza=?, lunghezza=?, trasversali=?, note=?, "
              "zona_id=?, modificata=? WHERE id = ?",
              (valori["articolo_id"], *[valori[c] for c in inventario.CAMPI], valori["note"], valori["zona_id"],
               db.adesso(), riga_id))
    return JSONResponse({"ok": True})


SELECT_RIGHE = (
    "SELECT r.*, a.codice, a.descrizione, a.unita, u.nome AS utente, z.nome AS zona "
    "FROM righe r JOIN articoli a ON a.id = r.articolo_id JOIN utenti u ON u.id = r.utente_id "
    "LEFT JOIN zone z ON z.id = r.zona_id WHERE r.inventario_id IS NULL ")


@api("operatore")
async def righe_mie(request, u):
    oggi = datetime.date.today().isoformat()
    righe = db.tutti(SELECT_RIGHE + "AND r.utente_id = ? AND r.creata >= ? ORDER BY r.creata DESC", (u["id"], oggi))
    return JSONResponse(righe)


@api("operatore")
async def segnala_articolo(request, u):
    dati = await request.json()
    testo = str(dati.get("testo") or "").strip()[:500]
    if not testo:
        raise Errore(400, "Descrivi l'articolo mancante")
    db.esegui("INSERT INTO notifiche (tipo, utente_id, testo, creata) VALUES ('articolo_mancante', ?, ?, ?)",
              (u["id"], f"Articolo mancante segnalato da {u['nome']}: {testo}", db.adesso()))
    return JSONResponse({"ok": True})


# --- Admin ------------------------------------------------------------------------
ORDINAMENTI = {"creata": "r.creata", "articolo": "a.codice", "utente": "u.nome", "zona": "z.nome"}


@api("admin")
async def admin_righe(request, u):
    q = request.query_params
    ordine = ORDINAMENTI.get(q.get("ordina", "creata"), "r.creata")
    verso = "ASC" if q.get("verso") == "asc" else "DESC"
    filtri, params = "", []
    if q.get("utente"):
        filtri += "AND r.utente_id = ? "
        params.append(int(q["utente"]))
    if q.get("zona"):
        filtri += "AND r.zona_id = ? "
        params.append(int(q["zona"]))
    if q.get("cerca"):
        filtri += "AND (a.codice LIKE ? OR a.descrizione LIKE ?) "
        params += [f"%{q['cerca']}%"] * 2
    return JSONResponse(db.tutti(SELECT_RIGHE + filtri + f"ORDER BY {ordine} {verso}, r.creata DESC", params))


@api("admin")
async def admin_notifiche(request, u):
    if request.method == "POST":
        db.esegui("UPDATE notifiche SET gestita_il = ?, gestita_da = ? WHERE id = ?",
                  (db.adesso(), u["id"], int(request.path_params["id"])))
        return JSONResponse({"ok": True})
    tutte = request.query_params.get("tutte") == "1"
    return JSONResponse(db.tutti(
        "SELECT n.*, u.nome AS utente FROM notifiche n LEFT JOIN utenti u ON u.id = n.utente_id "
        + ("" if tutte else "WHERE n.gestita_il IS NULL ") + "ORDER BY n.creata DESC LIMIT 500"))


@api("admin")
async def admin_stato(request, u):
    return JSONResponse({
        "notifiche": db.uno("SELECT COUNT(*) AS n FROM notifiche WHERE gestita_il IS NULL")["n"],
        "righe": db.uno("SELECT COUNT(*) AS n FROM righe WHERE inventario_id IS NULL")["n"],
    })


@api("admin")
async def admin_utenti(request, u):
    if request.method == "GET":
        return JSONResponse(db.tutti("SELECT id, nome, ruolo, attivo, creato FROM utenti ORDER BY ruolo DESC, nome"))
    dati = await request.json()
    utente_id = request.path_params.get("id")
    pin = str(dati.get("pin") or "")
    ruolo = dati.get("ruolo", "operatore")
    if ruolo not in ("operatore", "admin"):
        raise Errore(400, "Ruolo non valido")
    if pin:
        if ruolo == "operatore" and not (pin.isdigit() and len(pin) == 4):
            raise Errore(400, "Il PIN deve avere 4 cifre")
        if ruolo == "admin" and len(pin) < 8:
            raise Errore(400, "La password dell'admin deve avere almeno 8 caratteri")
    nome = str(dati.get("nome") or "").strip()
    if utente_id is None:
        if not nome or not pin:
            raise Errore(400, "Servono nome e PIN")
        if db.uno("SELECT id FROM utenti WHERE nome = ?", (nome,)):
            raise Errore(400, "Esiste già un utente con questo nome")
        db.esegui("INSERT INTO utenti (nome, ruolo, pin_hash, creato) VALUES (?, ?, ?, ?)",
                  (nome, ruolo, db.hash_pin(pin), db.adesso()))
        return JSONResponse({"ok": True})
    utente_id = int(utente_id)
    if utente_id == u["id"] and not dati.get("attivo", True):
        raise Errore(400, "Non puoi disattivare te stesso")
    if nome:
        db.esegui("UPDATE utenti SET nome = ? WHERE id = ?", (nome, utente_id))
    db.esegui("UPDATE utenti SET ruolo = ?, attivo = ? WHERE id = ?",
              (ruolo, 1 if dati.get("attivo", True) else 0, utente_id))
    if pin:
        db.esegui("UPDATE utenti SET pin_hash = ? WHERE id = ?", (db.hash_pin(pin), utente_id))
        db.esegui("DELETE FROM sessioni WHERE utente_id = ? AND token != ?", (utente_id, request.cookies.get(COOKIE)))
    if not dati.get("attivo", True):
        db.esegui("DELETE FROM sessioni WHERE utente_id = ?", (utente_id,))
    return JSONResponse({"ok": True})


@api("admin")
async def admin_articoli(request, u):
    if request.method == "GET":
        q = request.query_params.get("cerca", "")
        return JSONResponse(db.tutti(
            "SELECT * FROM articoli WHERE codice LIKE ? OR descrizione LIKE ? ORDER BY codice LIMIT 300",
            (f"%{q}%", f"%{q}%")))
    if request.method == "DELETE":
        articolo_id = int(request.path_params["id"])
        # Anche le righe archiviate puntano all'articolo: eliminarlo le lascerebbe senza articolo
        usato = db.uno("SELECT COUNT(*) AS n FROM righe WHERE articolo_id = ?", (articolo_id,))["n"]
        if usato:
            raise Errore(400, f"Articolo usato in {usato} righe di inventario: non si può eliminare, "
                              "togli la spunta \"Attivo\" per nasconderlo")
        db.esegui("DELETE FROM articoli WHERE id = ?", (articolo_id,))
        ricostruisci_indice()
        return JSONResponse({"ok": True})
    dati = await request.json()
    codice = str(dati.get("codice") or "").strip().upper()
    if not codice:
        raise Errore(400, "Il codice è obbligatorio")
    misure = [numero(dati.get(c), c) for c in db.MISURE]
    valori = (codice, str(dati.get("descrizione") or "").strip(), str(dati.get("unita") or "").strip(), *misure,
              1 if dati.get("misure_auto") else 0, str(dati.get("sinonimi") or "").strip(),
              1 if dati.get("attivo", True) else 0, db.adesso())
    articolo_id = request.path_params.get("id")
    altro = db.uno("SELECT id FROM articoli WHERE codice = ?", (codice,))
    if altro and str(altro["id"]) != str(articolo_id):
        raise Errore(400, "Esiste già un articolo con questo codice")
    if articolo_id is None:
        db.esegui("INSERT INTO articoli (codice, descrizione, unita, spessore, larghezza, lunghezza, trasversali, "
                  "misure_auto, sinonimi, attivo, modificato) VALUES (?,?,?,?,?,?,?,?,?,?,?)", valori)
    else:
        db.esegui("UPDATE articoli SET codice=?, descrizione=?, unita=?, spessore=?, larghezza=?, lunghezza=?, "
                  "trasversali=?, misure_auto=?, sinonimi=?, attivo=?, modificato=? WHERE id = ?",
                  (*valori, int(articolo_id)))
    ricostruisci_indice()
    return JSONResponse({"ok": True})


@api("admin")
async def admin_zone(request, u):
    if request.method == "GET":
        return JSONResponse(db.tutti("SELECT * FROM zone ORDER BY attiva DESC, nome"))
    dati = await request.json()
    if "id" in request.path_params:
        db.esegui("UPDATE zone SET attiva = ? WHERE id = ?",
                  (1 if dati.get("attiva") else 0, int(request.path_params["id"])))
    else:
        nome = str(dati.get("nome") or "").strip()
        if not nome:
            raise Errore(400, "Nome della zona mancante")
        db.esegui("INSERT INTO zone (nome) VALUES (?) ON CONFLICT(nome) DO UPDATE SET attiva = 1", (nome,))
    return JSONResponse({"ok": True})


def _csv(nome_file, intestazione, righe):
    buffer = io.StringIO()
    # ";" e virgola decimale: si apre direttamente con Excel in italiano
    scrittore = csv.writer(buffer, delimiter=";")
    scrittore.writerow(intestazione)
    def cella(v):
        if isinstance(v, float):
            return str(int(v)) if v.is_integer() else str(v).replace(".", ",")
        return "" if v is None else v
    for r in righe:
        scrittore.writerow([cella(v) for v in r])
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome_file}"'})


@api("admin")
async def admin_export(request, u):
    oggi = datetime.date.today().isoformat()
    righe = db.tutti(SELECT_RIGHE + "ORDER BY a.codice, r.creata")
    if request.path_params["tipo"] == "righe":
        return _csv(f"inventario-righe-{oggi}.csv",
                    ["Data", "Utente", "Zona", "Codice", "Descrizione", "Unità", "Pezzi", "Spessore (mm)",
                     "Larghezza (cm)", "Lunghezza (m)", "Trasversali (m)", "Totale", "Note"],
                    [[r["creata"].replace("T", " "), r["utente"], r["zona"], r["codice"], r["descrizione"], r["unita"],
                      r["pezzi"], r["spessore"], r["larghezza"], r["lunghezza"], r["trasversali"],
                      inventario.totale(r, r), r["note"]] for r in righe])
    # Totali per articolo
    totali = {}
    for r in righe:
        t = totali.setdefault(r["articolo_id"], {"r": r, "righe": 0, "pezzi": 0.0, "totale": 0.0, "senza_totale": 0})
        t["righe"] += 1
        t["pezzi"] += r["pezzi"] or 0
        tot = inventario.totale(r, r)
        if tot is None:
            t["senza_totale"] += 1
        else:
            t["totale"] += tot
    return _csv(f"inventario-totali-{oggi}.csv",
                ["Codice", "Descrizione", "Unità", "Righe", "Pezzi totali", "Quantità totale", "Righe senza misure"],
                [[t["r"]["codice"], t["r"]["descrizione"], t["r"]["unita"], t["righe"], round(t["pezzi"], 3),
                  round(t["totale"], 4) if inventario.scheda(t["r"])["totale"] else None, t["senza_totale"]]
                 for t in totali.values()])


@api("admin")
async def admin_chiudi(request, u):
    modo = (await request.json()).get("modo")
    if modo == "archivia":
        with db.transazione():
            cur = db.connessione().execute("INSERT INTO inventari (chiuso_il, chiuso_da) VALUES (?, ?)",
                                           (db.adesso(), u["id"]))
            db.connessione().execute("UPDATE righe SET inventario_id = ? WHERE inventario_id IS NULL", (cur.lastrowid,))
            db.connessione().execute("UPDATE notifiche SET gestita_il = ?, gestita_da = ? WHERE gestita_il IS NULL",
                                     (db.adesso(), u["id"]))
    elif modo == "cancella":
        with db.transazione():
            db.connessione().execute("DELETE FROM notifiche WHERE riga_id IN "
                                     "(SELECT id FROM righe WHERE inventario_id IS NULL)")
            db.connessione().execute("DELETE FROM righe WHERE inventario_id IS NULL")
    else:
        raise Errore(400, "Modo non valido")
    return JSONResponse({"ok": True})


ROUTES = [
    Route("/", pagina_home),
    Route("/login", pagina_login),
    Route("/operatore", pagina_operatore),
    Route("/admin", pagina_admin),
    Route("/static/{nome:str}", file_statico),
    Route("/sw.js", file_statico),
    Route("/api/utenti-accesso", utenti_accesso),
    Route("/api/accesso", accesso, methods=["POST"]),
    Route("/api/uscita", uscita, methods=["POST"]),
    Route("/api/io", chi_sono),
    Route("/api/catalogo", catalogo),
    Route("/api/voce", voce, methods=["POST"]),
    Route("/api/applica", applica, methods=["POST"]),
    Route("/api/righe", salva_riga, methods=["POST"]),
    Route("/api/righe/mie", righe_mie),
    Route("/api/righe/{id:str}", modifica_riga, methods=["PUT", "DELETE"]),
    Route("/api/segnalazioni", segnala_articolo, methods=["POST"]),
    Route("/api/admin/righe", admin_righe),
    Route("/api/admin/notifiche", admin_notifiche),
    Route("/api/admin/notifiche/{id:int}", admin_notifiche, methods=["POST"]),
    Route("/api/admin/stato", admin_stato),
    Route("/api/admin/utenti", admin_utenti, methods=["GET", "POST"]),
    Route("/api/admin/utenti/{id:int}", admin_utenti, methods=["PUT"]),
    Route("/api/admin/articoli", admin_articoli, methods=["GET", "POST"]),
    Route("/api/admin/articoli/{id:int}", admin_articoli, methods=["PUT", "DELETE"]),
    Route("/api/admin/zone", admin_zone, methods=["GET", "POST"]),
    Route("/api/admin/zone/{id:int}", admin_zone, methods=["PUT"]),
    Route("/api/admin/export/{tipo:str}", admin_export),
    Route("/api/admin/chiudi", admin_chiudi, methods=["POST"]),
]
