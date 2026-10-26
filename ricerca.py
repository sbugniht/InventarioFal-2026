"""Ricerca dell'articolo a partire da una frase ("performant strong 8 per 240").
Punteggio tipo BM25 sulle parole della descrizione, sui numeri, sul codice e sui sinonimi:
le parole rare ("larice", "vgz") pesano più di quelle comuni ("tavole", "vite").
Tollera piccoli errori di trascrizione (parole simili) e le lettere dettate una per una."""
import difflib
import math
import re
import unicodedata

PAROLE_VUOTE = {
    "di", "da", "del", "della", "dei", "delle", "e", "a", "al", "in", "per", "con", "il", "lo", "la", "le",
    "i", "gli", "un", "una", "uno", "mm", "cm", "m", "ml", "mt", "l", "x", "sp", "tipo", "fino", "articolo",
    "codice", "quello", "quella", "allora", "poi", "ecco", "ok",
}


def _senza_accenti(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _numero(tok: str) -> str:
    """'8,0' -> '8', '12,50' -> '12.5': così "8 per 240" trova "8,0X240"."""
    n = float(tok.replace(",", "."))
    return str(int(n)) if n.is_integer() else str(n)


SCELTE = {"i": "prima", "ii": "seconda", "iii": "terza", "iv": "quarta", "v": "quinta"}


def parole(testo: str) -> list[str]:
    t = _senza_accenti(testo.lower())
    # Scelta del legname come si dice: "I^" -> prima, "III^-IV^" -> terza quarta, "IV-V" -> quarta quinta
    t = re.sub(r"\b(iii|ii|iv|i|v)\^", lambda m: f" {SCELTE[m.group(1)]} ", t)
    t = re.sub(r"\b(iv)-(v)\b", " quarta quinta ", t)
    # Misure a coppie come parola unica: "8,0x240" e "8 per 240" -> "8x240" (distingue 6x6 da 2x6)
    coppie = [f"{_numero(a)}x{_numero(b)}"
              for a, b in re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:[x×*]|per)\s*(?=(\d+(?:[.,]\d+)?))", t)]
    # "roll-tech" -> anche "rolltech"; "8,0x240" -> "8,0 240"
    t = re.sub(r"(\d)\s*[x×*]\s*(?=\d)", r"\1 ", t)
    uniti = [a + b for a, b in re.findall(r"\b([a-z]+)[-/]([a-z]+)\b", t)]
    toks = []
    for tok in re.findall(r"[a-z]+|\d+(?:[.,]\d+)?", t) + uniti:
        if tok[0].isdigit():
            toks.append(_numero(tok))
            if tok.isdigit() and (tok.startswith("0") or len(tok) >= 5):
                toks.append(tok)  # codici numerici: "01280240" non deve perdere lo zero iniziale
        elif tok not in PAROLE_VUOTE:
            toks.append(tok)
    return toks + coppie


class Indice:
    def __init__(self, articoli: list[dict]):
        self.articoli = articoli
        self.doc = []
        df = {}
        for a in articoli:
            toks = set(parole(a["descrizione"]))
            toks |= set(parole(a.get("sinonimi", "").replace("|", " ")))
            codice = re.sub(r"[^a-z0-9]", "", a["codice"].lower())
            toks.add(codice)
            self.doc.append((toks, codice))
            for t in toks:
                df[t] = df.get(t, 0) + 1
        self.per_codice = {codice: a for a, (_, codice) in zip(articoli, self.doc)}
        # Codici che sono anche parole delle descrizioni ("pino", "murali"): detti, non bastano a scegliere
        self.codici_parola = {codice for _, codice in self.doc if df.get(codice, 0) > 1}
        n = max(len(articoli), 1)
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
        self.lunghezza_media = sum(len(d[0]) for d in self.doc) / n
        self.vocabolario_parole = [t for t in df if t.isalpha() and len(t) >= 4]

    def _parole_domanda(self, testo: str) -> dict[str, float]:
        toks = parole(testo)
        domanda = {}
        # Lettere dettate una per una o separate da Whisper: "v g z" -> "vgz"; cifre "0 1 2 8" -> "0128"
        corti = []
        for tok in toks + [""]:
            if len(tok) == 1:
                corti.append(tok)
                continue
            if len(corti) >= 2:
                domanda["".join(corti)] = 1.0
            corti = []
        # Parole attaccate: "roll tech" -> "rolltech", "pareti casa 240" -> codice "pareticasa240"
        for lunghezza in (2, 3, 4):
            for i in range(len(toks) - lunghezza + 1):
                unito = "".join(toks[i:i + lunghezza])
                if unito in self.idf:
                    domanda[unito] = 1.0
        for tok in toks:
            if tok in self.idf:
                domanda.setdefault(tok, 1.0)
            elif tok.isalpha() and len(tok) >= 4:
                # Errore di trascrizione: parola simile del catalogo, con peso ridotto
                for simile in difflib.get_close_matches(tok, self.vocabolario_parole, n=2, cutoff=0.8):
                    domanda.setdefault(simile, 0.7)
        return domanda

    def codice_detto(self, testo: str):
        """Codice dettato anche a pezzi: "M40-60-40", "L2, 304016", "L'AM40 24H", "a 3,25 e 40,20".
        Unisce fino a 6 pezzi consecutivi; vale il codice intero, oppure la parte finale ("40-24H")
        se è di un solo articolo. Torna (articolo, (inizio, fine) nel testo) oppure None."""
        pezzi = [m for m in re.finditer(r"[a-z0-9]+", testo.lower()) if m.group() != "e"]
        migliore = None  # (intero, lunghezza, articolo, inizio, fine)
        for i in range(len(pezzi)):
            unito = ""
            for j in range(i, min(i + 6, len(pezzi))):
                unito += pezzi[j].group()
                if len(unito) < 4 or not any(c.isdigit() for c in unito):
                    continue
                if unito in self.per_codice:
                    trovato = (1, len(unito), self.per_codice[unito])
                elif len(unito) >= 5 and (len(unito) >= 6 or not unito.isdigit()):
                    finali = [a for c, a in self.per_codice.items() if c.endswith(unito)]
                    if len(finali) != 1:
                        continue
                    trovato = (0, len(unito), finali[0])
                else:
                    continue
                if migliore is None or trovato[:2] > migliore[:2]:
                    migliore = (*trovato, pezzi[i].start(), pezzi[j].end())
        return (migliore[2], (migliore[3], migliore[4])) if migliore else None

    def cerca(self, testo: str, n: int = 6) -> list[dict]:
        domanda = self._parole_domanda(testo)
        if not domanda:
            return []
        k1, b = 1.2, 0.3
        numeri_detti = any(t[0].isdigit() for t in domanda)
        risultati = []
        for articolo, (toks, codice) in zip(self.articoli, self.doc):
            punteggio = 0.0
            for tok, peso in domanda.items():
                if tok in toks:
                    norm = (k1 + 1) / (1 + k1 * (1 - b + b * len(toks) / self.lunghezza_media))
                    punteggio += peso * self.idf.get(tok, 0) * norm
            if codice in domanda and codice not in self.codici_parola:
                punteggio += 20  # codice detto per intero: quasi certo
            if punteggio > 0 and numeri_detti:
                # Numeri dell'articolo non detti: "6 per 6" deve preferire 6x6 a 2x6
                # (se non si dice nessun numero, le descrizioni lunghe non vanno penalizzate)
                non_detti = sum(1 for t in toks if t[0].isdigit() and t not in domanda)
                punteggio -= 0.4 * non_detti
            if punteggio > 0:
                risultati.append((punteggio, articolo))
        risultati.sort(key=lambda r: r[0], reverse=True)
        return [{"punteggio": round(p, 2), **a} for p, a in risultati[:n]]


def sicuro(candidati: list[dict]) -> bool:
    """Il primo candidato stacca abbastanza il secondo?"""
    if not candidati:
        return False
    if len(candidati) == 1:
        return candidati[0]["punteggio"] >= 3
    return candidati[0]["punteggio"] >= 3 and candidati[0]["punteggio"] >= 1.2 * candidati[1]["punteggio"]
