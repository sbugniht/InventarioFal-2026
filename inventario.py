"""Dal testo dettato a una riga di inventario: articolo, quantità, misure, zona, note.

1. Regole (istantanee): parole chiave "pezzi", "spessore", "larghezza", "lunghezza", "trasversali",
   "sezione 64 per 32", "zona ...", "note ...", con numeri anche in lettere e unità ("300 centimetri").
   Il resto della frase serve a cercare l'articolo (ricerca.py).
2. Qwen (Ollama): solo se i primi articoli trovati sono troppo vicini, sceglie tra quelli.
Il risultato NON viene salvato qui: torna al tablet, che lo mostra per conferma."""
import difflib
import json
import os
import re
import unicodedata

import ricerca
from config import BASE_DIR, CONFIG

MISURE = ["spessore", "larghezza", "lunghezza", "trasversali"]
CAMPI = ["pezzi", *MISURE]

PAROLE_CHIAVE = [
    ("note", r"\bnot[ae]\b"),
    ("zona", r"\bzona\b"),
    ("sezione", r"\bsezione\b"),
    ("pezzi", r"\b(?:numero\s+(?:di\s+)?pezzi|pezz[oi]|pz|quantit[aà])\b"),
    ("spessore", r"\bspessor[ei]\b"),
    ("larghezza", r"\blarghezz[ae]\b"),
    ("lunghezza", r"\blunghezz[ae]\b"),
    ("trasversali", r"\btrasversal[ei]\b"),
]
UNITA_DETTE = {"millimetri": "mm", "millimetro": "mm", "mm": "mm", "centimetri": "cm", "centimetro": "cm",
               "cm": "cm", "metri": "m", "metro": "m", "mt": "m", "ml": "m", "m": "m"}
IN_METRI = {"mm": 0.001, "cm": 0.01, "m": 1.0}

with open(os.path.join(BASE_DIR, "dati", "regole_unita.json"), encoding="utf-8") as _f:
    REGOLE = json.load(_f)

# --- Numeri in lettere ---------------------------------------------------------
UNITA_NUM = {
    "zero": 0, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
    "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12,
    "tredici": 13, "quattordici": 14, "quindici": 15, "sedici": 16,
    "diciassette": 17, "diciotto": 18, "diciannove": 19,
}
DECINE = {
    "venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50,
    "sessanta": 60, "settanta": 70, "ottanta": 80, "novanta": 90,
}


def _senza_accenti(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def parola_a_numero(p: str) -> int | None:
    """'duecentocinquanta' -> 250, 'ventotto' -> 28, 'milleduecento' -> 1200."""
    p = _senza_accenti(p.lower())
    if not p:
        return None
    if p in UNITA_NUM:
        return UNITA_NUM[p]
    if "mila" in p:
        sx, dx = p.split("mila", 1)
        migliaia = parola_a_numero(sx)
        resto = parola_a_numero(dx) if dx else 0
        return None if migliaia is None or resto is None else migliaia * 1000 + resto
    if p.startswith("mille"):
        resto = parola_a_numero(p[5:]) if p[5:] else 0
        return None if resto is None else 1000 + resto
    if "cento" in p:
        sx, dx = p.split("cento", 1)
        centinaia = parola_a_numero(sx) if sx else 1
        resto = parola_a_numero(dx) if dx else 0
        return None if centinaia is None or resto is None else centinaia * 100 + resto
    for parola, valore in DECINE.items():
        # "ventuno", "trentotto": la vocale finale cade davanti a uno/otto
        for prefisso in (parola, parola[:-1]):
            if p.startswith(prefisso):
                resto = p[len(prefisso):]
                if not resto:
                    return valore if prefisso == parola else None
                if resto in UNITA_NUM and UNITA_NUM[resto] < 10:
                    return valore + UNITA_NUM[resto]
    return None


def _numeri_in_cifre(testo: str) -> str:
    """Converte i numeri in lettere e i decimali parlati ("2 virgola 5", "3 e mezzo")."""
    parole = []
    for parola in testo.split():
        n = parola_a_numero(parola.strip(".,;:"))
        parole.append(str(n) if n is not None else parola)
    testo = " ".join(parole)
    testo = re.sub(r"(\d+)\s+virgola\s+(\d+)", r"\1,\2", testo)
    testo = re.sub(r"(\d+)\s+e\s+mezz[oa]", r"\1,5", testo)
    return testo


def _a_numero(s: str) -> float | int:
    # "1.200" = milleduecento (separatore delle migliaia), "2,5" = due virgola cinque
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    n = float(s.replace(",", "."))
    return int(n) if n.is_integer() else n


NUMERO = r"(\d+(?:[.,]\d+)*)"
UNITA_RE = r"(?:\s*(millimetri|millimetro|mm|centimetri|centimetro|cm|metri|metro|mt|ml|m)\b)?"


def _valore_iniziale(valore: str):
    """Numero (con eventuale unità) subito dopo la parola chiave: (numero, unità, fine)."""
    m = re.match(r"^\s*[,:=]?\s*(?:di|da|è|e|uguale\s+a|pari\s+a)?\s*" + NUMERO + UNITA_RE, valore,
                 re.IGNORECASE)
    # "10 pezzi, 30 di spessore": quel 30 appartiene alla parola chiave successiva
    if not m or re.fullmatch(r"\s*di\s*[,.;]?\s*", valore[m.end():]):
        return None, None, 0
    unita = UNITA_DETTE.get((m.group(2) or "").lower())
    return _a_numero(m.group(1)), unita, m.end()


def _valore_finale(valore: str):
    """Numero alla fine del testo prima della parola chiave ("10 pezzi", "30 di spessore")."""
    m = re.search(NUMERO + UNITA_RE + r"\s*(?:di)?\s*[,.;]?\s*$", valore, re.IGNORECASE)
    if not m:
        return None, None, len(valore)
    return _a_numero(m.group(1)), UNITA_DETTE.get((m.group(2) or "").lower()), m.start()


# --- Estrazione dei valori dal testo -------------------------------------------
def estrai(testo: str, zone: list[dict] = ()) -> dict:
    """Valori detti (con le unità dette), zona, note e il testo che descrive l'articolo."""
    detti = {}
    risultato = {"detti": detti, "zona": None, "note": ""}
    testo = _numeri_in_cifre(testo.strip())

    nota = re.search(PAROLE_CHIAVE[0][1], testo, re.IGNORECASE)
    if nota:
        risultato["note"] = testo[nota.end():].strip(" :,.")
        testo = testo[:nota.start()]

    trovate = sorted(
        (m.start(), m.end(), campo)
        for campo, regex in PAROLE_CHIAVE[1:]
        for m in re.finditer(regex, testo, re.IGNORECASE)
    )
    segmenti, fine_precedente = [], -1
    for inizio, fine, campo in trovate:
        if inizio >= fine_precedente:  # tolgo le sovrapposizioni ("numero pezzi" contiene "pezzi")
            segmenti.append([campo, inizio, fine])
            fine_precedente = fine

    # Ogni parola chiave prende il testo fino alla successiva
    blocchi = [["preambolo", testo[:segmenti[0][1]] if segmenti else testo]]
    for i, (campo, _, fine) in enumerate(segmenti):
        fino_a = segmenti[i + 1][1] if i + 1 < len(segmenti) else len(testo)
        blocchi.append([campo, testo[fine:fino_a]])

    for i, (campo, valore) in enumerate(blocchi):
        if campo == "zona":
            parole_zona = re.sub(r"[^\w\s]", " ", valore).strip()
            nomi = {z["nome"].lower(): z for z in zone}
            # Provo prima due parole ("zona capannina nord"), poi una
            for n in (2, 1):
                candidato = " ".join(parole_zona.split()[:n]).lower()
                simili = difflib.get_close_matches(candidato, nomi.keys(), n=1, cutoff=0.75)
                if simili:
                    risultato["zona"] = nomi[simili[0]]
                    blocchi[i][1] = " ".join(parole_zona.split()[n:])
                    break
            else:
                blocchi[i][1] = ""
            continue
        if campo == "sezione":
            # "sezione 64 per 32": spessore x larghezza (ordine da confermare, vedi dati/README.md)
            m = re.match(r"^\s*" + NUMERO + UNITA_RE + r"\s*(?:per|x)\s*" + NUMERO + UNITA_RE, valore, re.IGNORECASE)
            if m:
                detti.setdefault("spessore", (_a_numero(m.group(1)), UNITA_DETTE.get((m.group(2) or "").lower())))
                detti.setdefault("larghezza", (_a_numero(m.group(3)), UNITA_DETTE.get((m.group(4) or "").lower())))
                blocchi[i][1] = valore[m.end():]
            continue
        if campo not in CAMPI:
            continue
        numero, unita, fine = _valore_iniziale(valore)
        if numero is not None:
            # Tolgo il numero usato: quello che resta può contenere il numero della parola chiave dopo
            blocchi[i][1] = valore[fine:]
        elif i > 0:
            # "10 pezzi", "lunghezza 4, 30 pezzi": il numero sta prima della parola chiave
            numero, unita, taglio = _valore_finale(blocchi[i - 1][1])
            if numero is not None:
                blocchi[i - 1][1] = blocchi[i - 1][1][:taglio]
        if numero is not None and campo not in detti:
            detti[campo] = (numero, unita)

    # Quello che resta (prima delle parole chiave e dopo i numeri) descrive l'articolo
    risultato["testo_articolo"] = " ".join(v for c, v in blocchi if c in ("preambolo", "articolo") or c in CAMPI
                                           or c == "sezione").strip(" ,.;")
    return risultato


# --- Scheda dell'articolo: campi obbligatori, misure fisse, unità --------------
def scheda(articolo: dict) -> dict:
    regola = REGOLE["unita"].get(articolo.get("unita") or "", REGOLE["unita"].get("Pz", {}))
    salvataggio = {c: REGOLE["salvataggio"].get(c, "m") for c in MISURE}
    parlato = dict(salvataggio)
    parlato.update(json.loads(articolo.get("parlato") or "{}"))
    return {
        "obbligatori": regola.get("obbligatori", ["pezzi"]),
        "fisse": {c: articolo[c] for c in MISURE if articolo.get(c) is not None},
        "misure_auto": bool(articolo.get("misure_auto")),
        "salvataggio": salvataggio,
        "parlato": parlato,
        "etichetta_pezzi": regola.get("etichetta_pezzi", "Pezzi"),
        "totale": regola.get("totale"),
        "unita_totale": {"Ml": "m", "Mq": "m²", "Mc": "m³"}.get(articolo.get("unita"), ""),
    }


def converti(valore, da, a):
    return round(valore * IN_METRI[da] / IN_METRI[a], 4)


def applica(articolo: dict, detti: dict) -> dict:
    """Valori detti + misure fisse dell'articolo -> campi nelle unità di salvataggio."""
    s = scheda(articolo)
    campi = {c: None for c in CAMPI}
    da_catalogo, conversioni = [], []
    for campo, (valore, unita) in detti.items():
        if campo == "pezzi":
            campi[campo] = valore
            continue
        destinazione = s["salvataggio"][campo]
        origine = unita or s["parlato"][campo]
        campi[campo] = converti(valore, origine, destinazione) if origine != destinazione else valore
        if origine != destinazione:
            conversioni.append(f"{campo}: {valore} {origine} → {campi[campo]} {destinazione}")
    for campo, valore in s["fisse"].items():
        if campi[campo] is None:  # quello detto vince su quello del catalogo
            campi[campo] = valore
            da_catalogo.append(campo)
    return {
        "campi": campi,
        "da_catalogo": da_catalogo,
        "conversioni": conversioni,
        "mancanti": [c for c in s["obbligatori"] if campi.get(c) is None],
        "scheda": s,
    }


def totale(articolo: dict, campi: dict):
    formula = scheda(articolo)["totale"]
    if not formula or any(campi.get(c) is None for c in CAMPI if c in formula):
        return None
    valori = {c: float(campi[c]) for c in CAMPI if campi.get(c) is not None}
    # Formula presa da dati/regole_unita.json (file locale fidato), senza funzioni disponibili
    return round(eval(formula, {"__builtins__": {}}, valori), 4)


# --- Scelta dell'articolo ------------------------------------------------------
def scegli_con_llm(testo: str, candidati: list[dict]) -> int | None:
    import ollama
    elenco = "\n".join(f"{i + 1}. {c['codice']} - {c['descrizione']} ({c['unita']})" for i, c in enumerate(candidati))
    risposta = ollama.chat(
        model=CONFIG["llm_modello"],
        messages=[
            {"role": "system", "content": (
                "Sei l'assistente di un magazzino di legname e ferramenta. Ricevi una frase dettata durante "
                "l'inventario e un elenco numerato di articoli. Scegli l'articolo di cui parla la frase. "
                "Se nessuno corrisponde rispondi null. Rispondi solo con il JSON.")},
            {"role": "user", "content": f"FRASE: {testo}\n\nARTICOLI:\n{elenco}"},
        ],
        format={"type": "object", "properties": {"scelta": {"type": ["integer", "null"]}}, "required": ["scelta"]},
        options={"temperature": 0},
        keep_alive=CONFIG["llm_keep_alive"],
    )
    scelta = json.loads(risposta.message.content).get("scelta")
    return scelta - 1 if isinstance(scelta, int) and 1 <= scelta <= len(candidati) else None


def _bonus_misure(articolo: dict, detti: dict) -> float:
    """"Larice spessore 60": premia gli articoli con spessore fisso 60 mm, penalizza quelli con un altro."""
    s = scheda(articolo)
    bonus = 0.0
    for campo, fisso in s["fisse"].items():
        if campo not in detti:
            continue
        valore, unita = detti[campo]
        origine, destinazione = unita or s["parlato"][campo], s["salvataggio"][campo]
        detto = converti(valore, origine, destinazione) if origine != destinazione else valore
        bonus += 4 if abs(detto - fisso) <= 0.01 * max(1, abs(fisso)) else -3
    return bonus


def analizza(testo: str, indice: ricerca.Indice, zone: list[dict] = ()) -> dict:
    estratto = estrai(testo, zone)
    candidati = indice.cerca(estratto["testo_articolo"] or testo, n=15)
    if estratto["detti"]:
        for c in candidati:
            c["punteggio"] = round(c["punteggio"] + _bonus_misure(c, estratto["detti"]), 2)
        candidati.sort(key=lambda c: c["punteggio"], reverse=True)
    candidati = candidati[:6]
    scelto, metodo, avviso = None, "voce:regole", None
    if candidati and ricerca.sicuro(candidati):
        scelto = 0
    elif candidati and CONFIG["llm_attivo"]:
        try:
            scelto = scegli_con_llm(testo, candidati)
            metodo = "voce:llm"
        except Exception as e:
            avviso = f"LLM non disponibile: {e}"
    if scelto is None and candidati:
        scelto, metodo = 0, "voce:incerto"

    risultato = {
        "testo": testo,
        "candidati": [{k: c[k] for k in ("id", "codice", "descrizione", "unita", "punteggio")} for c in candidati],
        "scelto": candidati[scelto]["id"] if scelto is not None else None,
        "metodo": metodo,
        "detti": {c: list(v) for c, v in estratto["detti"].items()},
        "zona": estratto["zona"],
        "note": estratto["note"],
        "avviso": avviso,
    }
    if scelto is not None:
        risultato.update(applica(candidati[scelto], estratto["detti"]))
    return risultato
