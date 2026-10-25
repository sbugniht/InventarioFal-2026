"""Misure fisse lette dalla descrizione dell'articolo ("sp. 200 mm", "27x205mm", "L=4m").
Prudente: prende un numero solo se ha l'unità scritta accanto, e salta le misure miste
("largh. mista", "16+") e i massimi ("fino a 8m"). Vale solo per Ml, Mq, Mc: per i pezzi
(viti, chiodi) le dimensioni nella descrizione identificano l'articolo, non sono misure da inventario.
I valori escono nelle unità di salvataggio: spessore mm, larghezza cm, lunghezza m."""
import re

UNITA_CON_MISURE = {"Ml", "Mq", "Mc"}
IN_METRI = {"mm": 0.001, "cm": 0.01, "m": 1.0}
SALVATAGGIO = {"spessore": "mm", "larghezza": "cm", "lunghezza": "m"}
NUM = r"(\d+(?:[.,]\d+)?)"


def _n(s):
    return float(s.replace(",", "."))


def converti(valore, da, campo):
    """Converte un valore da un'unità (mm/cm/m) a quella di salvataggio del campo."""
    a = SALVATAGGIO[campo]
    risultato = valore * IN_METRI[da] / IN_METRI[a]
    return round(risultato, 4)


def misure_da_descrizione(descrizione: str, unita: str) -> dict:
    if unita not in UNITA_CON_MISURE:
        return {}
    d = descrizione.lower()
    misure = {}

    # Tre dimensioni con unità (pannelli): "1250X600X100MM" -> lunghezza, larghezza, spessore
    m = re.search(NUM + r"\s*x\s*" + NUM + r"\s*x\s*" + NUM + r"\s*(mm|cm|m)\b", d)
    if m and unita == "Mq":
        lun, lar, spe = sorted((_n(m.group(i)) for i in (1, 2, 3)), reverse=True)
        u = m.group(4)
        misure.update(spessore=converti(spe, u, "spessore"), larghezza=converti(lar, u, "larghezza"),
                      lunghezza=converti(lun, u, "lunghezza"))
    elif unita == "Mq" and (m := re.search(r"\(\s*" + NUM + r"\s*x\s*" + NUM + r"\s*m\s*\)", d)):
        # Formato del pannello tra parentesi, in metri: "(2,05 x5,05m)" -> larghezza x lunghezza
        misure.update(larghezza=converti(_n(m.group(1)), "m", "larghezza"), lunghezza=_n(m.group(2)))
    if "larghezza" not in misure and not (m and unita == "Mq"):
        # Sezione con unità: "27x205mm", "6x6cm" -> spessore x larghezza (non seguita da un'altra "x")
        m = re.search(r"(?<![\d,.x/])" + NUM + r"\s*x\s*" + NUM + r"\s*(mm|cm)\b(?!\s*x)", d)
        if m:
            u = m.group(3)
            misure.update(spessore=converti(_n(m.group(1)), u, "spessore"),
                          larghezza=converti(_n(m.group(2)), u, "larghezza"))

    # Spessore: "sp. 200 mm", "sp.3cm", "mm 30", "mm.30"
    if "spessore" not in misure:
        m = re.search(r"\bsp\.?\s*" + NUM + r"\s*(mm|cm)\b", d)
        if m:
            misure["spessore"] = converti(_n(m.group(1)), m.group(2), "spessore")
        else:
            m = re.search(r"\bmm\.?\s*" + NUM + r"\b(?![.,]?\d*\s*x)", d)
            if m:
                misure["spessore"] = converti(_n(m.group(1)), "mm", "spessore")

    # Larghezza: "(larghezza1,22 m)", "largo cm 16" (non "16+", non "mista")
    if "larghezza" not in misure:
        m = re.search(r"\blargh(?:ezza)?\.?\s*" + NUM + r"\s*(mm|cm|m)\b(?!\s*\+)", d)
        if not m:
            m = re.search(r"\blargo\s*(mm|cm|m)\s*" + NUM + r"(?!\s*\+)\b", d)
            if m:
                misure["larghezza"] = converti(_n(m.group(2)), m.group(1), "larghezza")
        else:
            misure["larghezza"] = converti(_n(m.group(1)), m.group(2), "larghezza")

    # Lunghezza: "L=4m", "ml 3" (non "fino a ml 13", non "fino a 8m")
    if "lunghezza" not in misure:
        m = re.search(r"\b(?:l\s*=|lungh\.?)\s*" + NUM + r"\s*m\b", d)
        if m:
            misure["lunghezza"] = _n(m.group(1))
        else:
            m = re.search(r"(?<!fino a )\bml\s*" + NUM + r"\b", d)
            if m:
                misure["lunghezza"] = _n(m.group(1))
    return misure
