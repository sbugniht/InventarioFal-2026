"""Controlla la cartella dati/ e dice cosa manca ancora o è sbagliato.
Uso:  venv/bin/python controlla_dati.py"""
from collections import Counter

from catalogo import Catalogo, MISURE

MAX_PAROLE_VOCABOLARIO = 150


def titolo(testo):
    print(f"\n=== {testo} ===")


def main():
    cat = Catalogo()
    da_fare = []

    titolo("Articoli")
    if cat.file_articoli == "articoli.esempio.csv":
        print("⚠️  Uso il file di ESEMPIO (articoli.esempio.csv).")
        da_fare.append("Esportare la tabella articles da phpMyAdmin in dati/articoli.csv")
    print(f"File: {cat.file_articoli} · articoli attivi: {len(cat.articoli)}")
    unita = Counter(a["unit"] for a in cat.articoli)
    note_regole = cat.regole.get("unita", {})
    for u, n in unita.most_common():
        stato = "ok" if u in note_regole else "❌ NON definita in regole_unita.json"
        print(f"  {u or '(vuota)':6} {n:5} articoli  · {stato}")
        if u not in note_regole:
            da_fare.append(f"Aggiungere l'unità '{u}' a regole_unita.json")

    titolo("Regole per unità")
    salvataggio = cat.regole.get("salvataggio", {})
    print("Unità di salvataggio: " + ", ".join(f"{c} {salvataggio.get(c, '?')}" for c in MISURE)
          + ("  (da verificare)" if salvataggio.get("da_verificare") else ""))
    if salvataggio.get("da_verificare"):
        da_fare.append("Confermare le unità di salvataggio dei campi (regole_unita.json → salvataggio)")
    for u, regola in note_regole.items():
        flag = "  (da verificare)" if regola.get("da_verificare") else ""
        print(f"  {u}: obbligatori {', '.join(regola.get('obbligatori', []))} · totale {regola.get('totale')}{flag}")
        if regola.get("da_verificare"):
            da_fare.append(f"Confermare campi e totale per l'unità {u}")

    titolo("Misure per articolo (misure_articoli.csv)")
    for codice, voce in cat.misure_esatte.items():
        if codice not in cat.per_codice:
            print(f"  ❌ riga {voce['riga']}: il codice {codice} non esiste nel catalogo")
        if "DA VERIFICARE" in voce["note"].upper() or "ESEMPIO" in voce["note"].upper():
            print(f"  ⚠️  riga {voce['riga']} {codice}: {voce['note']}")
    for voce in cat.misure_famiglie:
        n = sum(1 for c in cat.per_codice if c.startswith(voce["codice"][:-1]))
        segno = "❌" if n == 0 else "  "
        print(f"  {segno} famiglia {voce['codice']}: {n} articoli" + (f" · {voce['note']}" if voce["note"] else ""))
    # Per ogni unità: quanti articoli richiedono di dire tutte le misure
    senza_misure = Counter()
    for a in cat.articoli:
        scheda = cat.scheda(a)
        if any(c in scheda["da_dire"] for c in MISURE):
            senza_misure[a["unit"]] += 1
    for u, n in senza_misure.most_common():
        print(f"  {u}: {n} articoli con almeno una misura da dire ogni volta")
    if senza_misure:
        da_fare.append("Completare le misure fisse dal CRM dove esistono (misure_articoli.csv o colonne di articles)")

    titolo("Zone")
    print("  " + (", ".join(cat.zone) or "nessuna"))

    titolo("Vocabolario per Whisper")
    parole = len(cat.vocabolario.replace(",", " ").split())
    print(f"  {parole} parole" + ("  ⚠️ troppe, Whisper ne usa ~150" if parole > MAX_PAROLE_VOCABOLARIO else ""))

    titolo("Errori nei file")
    for p in cat.problemi:
        print(f"  ❌ {p}")
    if not cat.problemi:
        print("  nessuno")

    titolo("Ancora da fare")
    for voce in dict.fromkeys(da_fare):
        print(f"  [ ] {voce}")
    print("  [ ] Ordine della sezione dettata (\"64 per 32\") e significato di Trasversali  (vedi dati/README.md)")


if __name__ == "__main__":
    main()
