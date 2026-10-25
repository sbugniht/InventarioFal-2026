# Dati aziendali da completare

Questa cartella contiene tutto ciò che il sistema deve sapere sull'azienda.
Si compila **senza toccare il codice**. Dopo ogni modifica lancia il controllo:

```bash
venv/bin/python controlla_dati.py
```

Elenca cosa manca ancora e gli errori nei file (righe sbagliate, codici inesistenti, unità sconosciute).

---

## Checklist per la visita in azienda

### 1. Catalogo articoli — `articoli.csv`
- [ ] Altervista → phpMyAdmin → tabella `articles` → **Esporta** → formato **CSV** → salva qui come `articoli.csv`
      (va bene sia con che senza la riga di intestazione, separatore `,` o `;`).
      Serve **una volta sola**: dopo l'import gli articoli si modificano a mano dalla schermata admin sul PC.
- Finché manca, il sistema usa `articoli.esempio.csv` (poche righe vere copiate a mano).

### 2. Unità e campi obbligatori — `regole_unita.json`
Per ogni unità (Pz, Ml, Mq, Mc) quali campi servono e come si calcola il totale.
- [ ] **Pz**: basta il numero di pezzi?
- [ ] **Ml**: pezzi + lunghezza di ciascuno, oppure solo i metri totali?
- [ ] **Mq**: pezzi + larghezza + lunghezza, oppure solo i m² totali?
- [ ] **Mc**: pezzi + spessore + larghezza + lunghezza (il volume lo calcola il sistema)?
- [ ] Ci sono altre unità oltre a Pz, Ml, Mq, Mc?
- [ ] In che unità vanno **salvati** i campi su Altervista? (il vecchio modulo dice: spessore mm, larghezza cm,
      lunghezza m, trasversali m)
- [ ] Cosa significa **Trasversali** e per quali articoli si usa?
- Quando un valore è confermato, metti `"da_verificare": false`.

### 3. Misure fisse e unità parlate per articolo — `misure_articoli.csv`
Una riga per articolo **o per famiglia** (codice che finisce con `*`, es. `UF*` = tutti i codici che iniziano con UF).
- Colonne `spessore`, `larghezza`, `lunghezza`, `trasversali`: valore **fisso** dell'articolo (nell'unità di
  salvataggio). **Vuoto = va detto ogni volta** (es. `LAM4024H`, sezione variabile).
- Colonne `parlato_*`: unità in cui la gente dice quel numero se non specifica (`mm`, `cm`, `m`).
  Vuoto = quella di `regole_unita.json`.
- Colonna `sinonimi`: come chiamano l'articolo a voce, separati da `|` (es. `rolltech nero|roll tech nero`).
- [ ] Prendere le misure dal **CRM** dove esistono.
- [ ] Decidere l'**ordine** con cui si detta una sezione: "64 per 32" = spessore × larghezza o il contrario?
- [ ] Per quali famiglie la larghezza si dice in mm (minuteria, tavole) e per quali in cm?

### 4. Zone — `zone.txt`
- [ ] Una zona per riga (Polmone, Capannina, …). Si possono aggiungere anche dal tablet.

### 5. Parole suggerite a Whisper — `vocabolario.txt`
- [ ] Nomi delle famiglie e termini di magazzino come li dicono le persone (max ~150 parole: Whisper non ne
      accetta di più). Aiuta a scriverli giusti.

### 6. Varie
- [ ] Utenti (Nicola, Gino, Mirco, Tiziano, Franco, Gabriele, Mattia, Michele + admin): li crei tu dalla
      schermata admin sul PC, quando sarà pronta.
- [ ] PC di produzione: modello della scheda NVIDIA e memoria video (Gestione attività → Prestazioni → GPU).
- [ ] Tablet usati: modello (iPad / Android), quanti, se hanno la penna.
- [ ] Cartella del **NAS** per i backup del database.
- [ ] Chi riceve l'inventario finito (contabilità / CRM) e in che **formato** lo vuole (colonne, Excel/CSV,
      righe singole o totali per articolo / zona).
- [ ] Copertura Wi-Fi nelle zone di magazzino.
- [ ] Eventuale CSV dell'inventario degli anni scorsi (`filename.csv` nei Download del PC dell'ufficio).
- [ ] (Facoltativo) chi gestisce il **DNS** del dominio aziendale, per un certificato senza installazioni sui tablet.

Le decisioni prese e quelle ancora aperte sono in [PROGETTO.md §15](../PROGETTO.md#15-decisions).
