"""Catalogo aziendale letto dalla cartella dati/ (vedi dati/README.md).

- articoli.csv           export phpMyAdmin della tabella articles (altrimenti articoli.esempio.csv)
- regole_unita.json      unità di salvataggio, campi obbligatori e totale per Pz/Ml/Mq/Mc
- misure_articoli.csv    misure fisse, unità parlate e sinonimi per articolo o famiglia (codice*)
- zone.txt, vocabolario.txt
Ogni problema trovato nei file finisce in Catalogo.problemi (lo mostra controlla_dati.py)."""
import csv
import io
import json
import os

from config import BASE_DIR

DATI_DIR = os.path.join(BASE_DIR, "dati")

# Campi di una riga di inventario (nome usato a voce/nei file -> colonna del database)
CAMPI = {
    "pezzi": "num_items",
    "spessore": "thickness",
    "larghezza": "width",
    "lunghezza": "length",
    "trasversali": "transversal",
}
MISURE = ["spessore", "larghezza", "lunghezza", "trasversali"]
UNITA_LUNGHEZZA = {"mm": 0.001, "cm": 0.01, "m": 1.0}

# Ordine delle colonne della tabella articles, per l'export CSV senza intestazione
COLONNE_ARTICLES = ["id", "date_created", "date_modified", "code", "code_search", "description",
                    "unit", "thickness", "width", "length", "transversal", "enabled"]


def _numero(valore):
    if valore is None:
        return None
    valore = str(valore).strip()
    if valore == "" or valore.upper() == "NULL":
        return None
    return float(valore.replace(",", "."))


def _leggi_csv(percorso):
    with open(percorso, encoding="utf-8-sig", newline="") as f:
        testo = f.read()
    # Il separatore si deduce dalla prima riga: phpMyAdmin usa "," ed Excel italiano ";"
    prima = testo.split("\n", 1)[0]
    separatore = max(",;\t", key=prima.count) if prima else ";"
    return list(csv.reader(io.StringIO(testo), delimiter=separatore))


def _righe_non_vuote(percorso):
    if not os.path.exists(percorso):
        return []
    with open(percorso, encoding="utf-8") as f:
        return [r.strip() for r in f if r.strip() and not r.lstrip().startswith("#")]


class Catalogo:
    def __init__(self, cartella=DATI_DIR):
        self.cartella = cartella
        self.problemi = []
        self.articoli = []
        self.file_articoli = None
        self.regole = {}
        self.misure_esatte = {}
        self.misure_famiglie = []
        self._carica_articoli()
        self._carica_regole()
        self._carica_misure()
        self.zone = _righe_non_vuote(os.path.join(cartella, "zone.txt"))
        self.vocabolario = ", ".join(_righe_non_vuote(os.path.join(cartella, "vocabolario.txt")))

    # --- caricamento -------------------------------------------------------------
    def _carica_articoli(self):
        for nome in ("articoli.csv", "articoli.esempio.csv"):
            percorso = os.path.join(self.cartella, nome)
            if os.path.exists(percorso):
                self.file_articoli = nome
                break
        else:
            self.problemi.append("Nessun file articoli (articoli.csv) in dati/")
            return

        righe = _leggi_csv(os.path.join(self.cartella, self.file_articoli))
        if righe and "code_search" in [c.strip().lower() for c in righe[0]]:
            intestazione = [c.strip().lower() for c in righe.pop(0)]
        else:
            intestazione = COLONNE_ARTICLES
        for n, riga in enumerate(righe, start=2):
            if not any(c.strip() for c in riga):
                continue
            if len(riga) != len(intestazione):
                self.problemi.append(f"{self.file_articoli} riga {n}: {len(riga)} colonne invece di {len(intestazione)}")
                continue
            r = dict(zip(intestazione, riga))
            try:
                articolo = {
                    "id": int(r["id"]),
                    "code": r.get("code", "").strip(),
                    "code_search": r["code_search"].strip(),
                    "description": r.get("description", "").strip(),
                    "unit": r.get("unit", "").strip(),
                    "enabled": r.get("enabled", "1").strip() != "0",
                }
                for campo in MISURE:
                    articolo[CAMPI[campo]] = _numero(r.get(CAMPI[campo]))
            except (KeyError, ValueError) as e:
                self.problemi.append(f"{self.file_articoli} riga {n}: valore non valido ({e})")
                continue
            if articolo["enabled"]:
                self.articoli.append(articolo)
        self.per_codice = {a["code_search"].upper(): a for a in self.articoli}

    def _carica_regole(self):
        percorso = os.path.join(self.cartella, "regole_unita.json")
        try:
            with open(percorso, encoding="utf-8") as f:
                self.regole = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.problemi.append(f"regole_unita.json non leggibile: {e}")
            self.regole = {"salvataggio": {}, "unita": {}}

    def _carica_misure(self):
        percorso = os.path.join(self.cartella, "misure_articoli.csv")
        if not os.path.exists(percorso):
            return
        righe = _leggi_csv(percorso)
        if not righe:
            return
        intestazione = [c.strip().lower() for c in righe.pop(0)]
        for n, riga in enumerate(righe, start=2):
            if not any(c.strip() for c in riga):
                continue
            r = dict(zip(intestazione, [c.strip() for c in riga]))
            codice = r.get("codice", "").upper()
            if not codice:
                self.problemi.append(f"misure_articoli.csv riga {n}: codice mancante")
                continue
            voce = {"codice": codice, "riga": n, "fisse": {}, "parlato": {},
                    "sinonimi": [s.strip() for s in r.get("sinonimi", "").split("|") if s.strip()],
                    "note": r.get("note", "")}
            for campo in MISURE:
                try:
                    valore = _numero(r.get(campo))
                except ValueError:
                    self.problemi.append(f"misure_articoli.csv riga {n}: {campo} non è un numero")
                    valore = None
                if valore is not None:
                    voce["fisse"][campo] = valore
                unita = r.get(f"parlato_{campo}", "")
                if unita:
                    if unita not in UNITA_LUNGHEZZA:
                        self.problemi.append(f"misure_articoli.csv riga {n}: unità '{unita}' sconosciuta "
                                             f"(usa mm, cm o m)")
                    else:
                        voce["parlato"][campo] = unita
            if codice.endswith("*"):
                self.misure_famiglie.append(voce)
            else:
                self.misure_esatte[codice] = voce
        # La famiglia più specifica (prefisso più lungo) vince
        self.misure_famiglie.sort(key=lambda v: len(v["codice"]), reverse=True)

    # --- uso ---------------------------------------------------------------------
    def voci_misure(self, codice):
        """Voci di misure_articoli.csv che valgono per un codice: prima l'articolo, poi le famiglie."""
        codice = codice.upper()
        voci = [v for v in self.misure_famiglie if codice.startswith(v["codice"][:-1])]
        if codice in self.misure_esatte:
            voci.insert(0, self.misure_esatte[codice])
        return voci

    def scheda(self, articolo):
        """Tutto quello che serve al modulo per un articolo: campi obbligatori, misure fisse,
        unità in cui si dicono i numeri, sinonimi, formula del totale."""
        regola = self.regole.get("unita", {}).get(articolo["unit"], {})
        salvataggio = {c: u for c, u in self.regole.get("salvataggio", {}).items() if c in MISURE}
        fisse = {c: articolo[CAMPI[c]] for c in MISURE if articolo.get(CAMPI[c]) is not None}
        parlato = dict(salvataggio)
        sinonimi = []
        # Dalla famiglia più generica all'articolo: il più specifico sovrascrive
        for voce in reversed(self.voci_misure(articolo["code_search"])):
            fisse.update(voce["fisse"])
            parlato.update(voce["parlato"])
            sinonimi += voce["sinonimi"]
        obbligatori = regola.get("obbligatori", ["pezzi"])
        return {
            "articolo": articolo,
            "obbligatori": obbligatori,
            "da_dire": [c for c in obbligatori if c != "pezzi" and c not in fisse] + (["pezzi"] if "pezzi" in obbligatori else []),
            "fisse": fisse,
            "unita_salvataggio": salvataggio,
            "unita_parlate": parlato,
            "sinonimi": sinonimi,
            "totale": regola.get("totale"),
        }


def carica():
    return Catalogo()
