# Inventario vocale — how everything works

Living design document. **❓** = still open: data to collect is in [dati/README.md](dati/README.md),
decisions taken and still open are in [§15](#15-decisions).

---

## 1. Goal

During the yearly inventory, the people counting the material record each line **right after counting it**,
on a tablet or phone, by **voice** or **by hand** — instead of writing on paper and retyping everything at the
end of the day.

Everything runs on **one company PC**: the tablet page, speech recognition, the database (SQLite) and the admin
screens. **Altervista is no longer used** for the inventory: the article list is exported from it once, then
maintained on the PC.

## 2. Who and what

| Part | What it is | Where it runs |
|---|---|---|
| **Inventory staff** | ~8 people (Nicola, Gino, Mirco, Tiziano, Franco, Gabriele, Mattia, Michele) + admin | Tablets / phones on the company Wi-Fi |
| **Inventory server** | Python: tablet page, admin screens, Whisper (speech → text), article matching, Qwen (only when unsure) | Company PC (production) / Mac (development) |
| **Database** | SQLite: one file on the PC (`inventario.db`), backed up automatically | Company PC |
| **CRM** | Source of article measures (copied by hand when needed) | Company |

```
 tablets / phones (company Wi-Fi)              company PC
 ┌──────────────────────────┐   HTTPS   ┌────────────────────────────────────┐
 │ inventory page           │ ────────▶ │ inventory server                   │
 │ • 🎤 Registra / by hand   │ ◀──────── │ • Whisper → text                   │
 │ • check, Salva, correct  │           │ • article matching (+ Qwen)        │
 │ • offline queue          │           │ • measures/units from the catalog  │
 └──────────────────────────┘           │ • admin: users, articles, lines,   │
 ┌──────────────────────────┐           │   export CSV/Excel                 │
 │ admin (office PC/browser)│ ────────▶ │ SQLite inventario.db ──▶ backup NAS│
 └──────────────────────────┘           └────────────────────────────────────┘
```

## 3. Recording one line

1. The person picks **their name from the list** of users and types their **4-digit PIN** (on the built-in
   number pad). The device remembers them until they log out.
2. Optionally sets the **zone** by voice ("zona polmone"). It stays until changed. ([§7](#7-zones))
3. Taps **🎤 Registra**, speaks, taps again to stop. The microphone is only on between the two taps.
   Example: *"Roll-tech 310 nero, 4 pezzi, lunghezza 25"*.
4. Under the button the page shows:
   - **What Whisper heard** (raw text);
   - **The chosen article** — code + full description — and *who* picked it (algorithm or Qwen),
     plus the **next 3–5 closest articles** to tap if the first is wrong;
   - **The fields for that article**, filled with what was said and with the article's fixed measures
     ([§6](#6-measures-and-units)); missing required fields highlighted.
5. **Salva** → stored on the device, beep + green flash with the article name (every time, even for the same
   article), sent to the PC automatically. Once on the PC the line is final — no further import step.

**Manual entry** works the same way without the microphone: search the article by code or words of the
description, the fixed measures fill in, the rest is typed on the built-in number pad.

## 4. Speech to text (Whisper)

- Runs on the PC, not on the tablet. One recording at a time (queue).
- Engine chosen automatically: Apple MLX on the Mac, NVIDIA CUDA if there is an RTX card, otherwise CPU.
- Gets a short list of **hint words** (product families, trade terms) — [dati/vocabolario.txt](dati/vocabolario.txt).
  It cannot be given all ~2000 articles.
- **Audio is never kept**: deleted right after transcription. The **transcribed text is kept** with the line
  it produced, for checking — see [§13](#13-privacy-gdpr) for how long.
- Unloaded from memory after a few idle minutes, so it does not slow down AutoCAD / SketchUp / Excel.

## 5. Choosing the article

The catalog has **~2000 articles**, many nearly identical (same family, different length/section/colour).
Codes are mostly numeric (`01280240`) or mnemonic (`UF12508`, `PARETICASA240`, `LAM4024H`); people will mostly
say **the description**, not the code.

1. **Algorithm (always, instant):** scores every article on
   - product family / words of the description and spoken names ("performant strong", "uso fiume", "larice");
   - dimensions said ("8 per 240" ↔ `8,0X240`);
   - the code, if someone reads it;
   - whether the measures said fit the article's unit.
2. **Qwen (only when the top candidates are close):** gets the text and the **shortlist (5–10)**, never the whole
   catalog, and picks one.
3. The page always shows the choice, who made it, and the alternatives. The person has the last word.

## 6. Measures and units

Fields of an inventory line: **pezzi, spessore, larghezza, lunghezza, trasversali, note, zona**.

**Article unit:** `Pz` pieces · `Ml` linear metres · `Mq` square metres · `Mc` cubic metres.

**Measures that follow the article:**

| Article measure | Behaviour |
|---|---|
| **Filled** (e.g. `PARETICASA240` → spessore 240 mm) | Filled in automatically when the article is chosen (by voice or by hand). Can be overwritten. |
| **Empty** (e.g. `LAM4024H` = any beam with 40 mm lamella, GL24H — section varies) | **Must be said or typed.** Highlighted; saving without it gives a different beep and "manca: …". |

Rule: **what is said wins** over the stored value.

**Units of the numbers** (proposed, ❓ to confirm):
- Each field is **stored** in one fixed unit (old form: spessore mm, larghezza cm, lunghezza m, trasversali m).
- Each article or family has a **default spoken unit** per field: a bare number is read in that unit
  (e.g. small items' width in mm, planks' width in cm).
- A unit that is said ("300 centimetri") is converted to the stored unit; the conversion is shown.

**Required fields and totals** (proposed defaults, ❓ to confirm with CRM data):

| Unit | Required | Total shown |
|---|---|---|
| Pz | pezzi | — |
| Ml | pezzi + lunghezza | m |
| Mq | pezzi + larghezza + lunghezza | m² |
| Mc | pezzi + spessore + larghezza + lunghezza | m³ |

**Where the article data lives:** imported **once** from Altervista (`dati/articoli.csv`) together with
`dati/misure_articoli.csv` and `dati/regole_unita.json`; after that, articles and measures are edited
**by hand in the admin screen** on the PC.

**New articles:** only the admin can create them. If staff find something that is not in the catalog they use
**"Segnala articolo mancante"** (description + note, optional photo later) → it appears in the admin's
notifications ([§11](#11-admin-screens-on-the-pc-from-any-browser-on-the-company-network)).

## 7. Zones

- Optional, **said by the person** ("zona polmone", "zona capannina"). No GPS, no automatic location.
- Stays set on the device until a different zone is said; shown on every line.
- Starting list in [dati/zone.txt](dati/zone.txt); new zones can be added from the tablet or the admin screen.

## 8. Saving and offline

- **One Salva button.** The line is stored on the device first, then sent to the PC automatically.
  Indicator: "✓ inviato" / "3 in attesa".
- **Wi-Fi drops:** the page still opens (cached), manual entry works fully, voice recordings wait in a queue and
  come back as "da confermare" when the connection returns. Each line has a unique id → no duplicates.
- **Backup:** built in but **switched off** until the NAS folder is known. Then: a copy of `inventario.db` every
  hour during working hours + one every night, copies older than 30 days deleted. Only `config.json` changes
  (`backup_cartella`).

## 9. Corrections

- Under the form: **today's lines** of that person, newest first — tap to edit, delete, **"Annulla ultimo"**.
- Correction by voice: *"correggi: pezzi 14"*.
- **Each person can change only their own lines**; the admin can change any line.

## 10. Tablet page

- Tablet-first: big buttons, usable with a stylus or touchscreen gloves (winter).
- **Built-in number pad** → the system keyboard does not pop up and cover the form.
- Normal text fields → iPad Scribble / Samsung pen handwriting work in them.
- Sounds: beep on save, different sound on error / missing field.

## 11. Admin screens (on the PC, from any browser on the company network)

Replace what Altervista did, plus the notes' requests. The admin page is usually left open in the background
and looked at at the end of the day, so anything that needs attention **stays visible until handled**.

- **Notifications ("Da controllare")** — a permanent badge with the count in the page header and a panel
  listing each item; an item disappears only when the admin marks it **handled** (and the badge also shows in
  the browser tab title, so it is visible with the page in the background):
  - **possible duplicate**: same article + zone + measures saved within a few minutes (the line is still saved —
    two packs of the same article are normal);
  - **missing article** reported by staff ([§6](#6-measures-and-units));
  - room for more later (e.g. lines where the article was chosen with low confidence).
- **Users:** create / disable, set or reset the PIN (the admin sets them up — Nicola, Gino, …).
- **Articles:** list, search, edit measures / spoken units / spoken names, **add new articles (admin only)**.
- **Zones:** list, add, disable.
- **Lines:** full list, **sort by insertion date** (also article, user, zone), filter, edit, delete.
- **Export CSV — totals per article:** code, description, unit, total pieces, total quantity in the article's
  unit (m / m² / m³ where it applies). Later: comparison with the CRM stock to show discrepancies.
- **Close the inventory:** one button, two choices —
  **"Archivia con data"** (lines kept, tagged with the closing date, list emptied for the next inventory) or
  **"Cancella"** (lines deleted, with a second confirmation).

## 12. The PC

**Chosen: Core Ultra + RTX (8 GB VRAM, to confirm).** Whisper large-v3-turbo on the GPU (~1.5 GB) + Qwen 2.5 3B
(~2.5 GB) only when needed → ≤ ~4 GB, both unloaded after a few idle minutes, server at low priority, so AutoCAD /
SketchUp keep at least half the video memory. Fallback if needed: Qwen on the CPU.
The i7-13700 tower stays as plan B (everything on CPU, ~2–6 s per line).

- Fixed LAN IP (DHCP reservation), Windows service starting at boot, firewall rule for the port.
- **It must be on during the inventory**: it is now the only system.
- HTTPS is mandatory (microphone, offline mode):
  - now: own local certificate authority — installed once on each tablet;
  - optional later: Let's Encrypt certificate on a company subdomain, nothing to install on tablets.
- Settings in `config.json` (see `config.example.json`).

## 13. Privacy (GDPR)

*Not legal advice — to be confirmed with the company's privacy / labour consultant.*

**What is personal data here:** every line says **who** counted **what** and **when** (and the zone they said);
the kept transcript is that person's spoken words. These are personal data of the employees (GDPR art. 4),
not special categories: no audio is kept, no GPS, no voice identification.

**Why it can be done:** the app is a **work tool** used to do the job (art. 4, comma 2 of the Statuto dei
Lavoratori), so no union agreement is needed. Lawful basis: the employment relationship / the company's
legitimate interest in an accurate inventory (GDPR art. 6.1.b/f).

**What the company must do:**
- give the 8 people a short **written information notice** (GDPR art. 13; also required by art. 4 comma 3
  of the Statuto for the data to be usable): what is recorded (name, time, line, transcript, zone said), why,
  who sees it (admin), how long it is kept, that audio is not kept;
- add the processing to the company's **record of processing** (art. 30), if it keeps one;
- keep it **minimal and secure**: no audio, no location, company network only, PIN, backups on the NAS.

**How long** (GDPR art. 5.1.e — as long as needed for the purpose, no fixed legal term):
- **Audio:** never stored.
- **Transcripts:** needed only to check and correct the count → kept until the inventory is **closed and
  reconciled with the CRM**, then **deleted automatically after 90 days** (setting `trascrizioni_giorni`).
- **Inventory lines** (article, quantities, measures, who, when, zone): kept with the archived inventory. The
  yearly inventory supports the accounts, which are normally kept for **10 years** (codice civile art. 2220) —
  the consultant should confirm whether the per-person detail must stay that long or can be reduced to totals.

## 14. Status

| Area | Status |
|---|---|
| Server: Whisper portable (MLX/CUDA/CPU), idle unload, low priority | ✅ built, tested on Mac |
| `/api/inventario` (audio/text → fields) | ✅ built, tested on Mac |
| Rule parser: numbers in words, decimals, "10 pezzi"/"pezzi 10", spelled codes | ✅ built, tested |
| Catalog loader + data checker (`catalogo.py`, `controlla_dati.py`) | ✅ built, tested on sample data |
| Matching by **description** over the real catalog (1760 articles), measures said used to pick, Qwen when unsure | ✅ built, tested with spoken Italian on Mac |
| Autofill of measures from descriptions (~470 Ml/Mq/Mc articles, flagged "auto" for checking) | ✅ built |
| SQLite database (users + PIN, articles, zones, lines, notifications, archive) + one-time import | ✅ built, tested |
| Login page (name + PIN pad, admin password) | ✅ built, tested in browser |
| Operator page (Registra → Ferma → Salva, check/correct, manual entry, offline queue, today's lines, report missing article) | ✅ built, tested in browser |
| Admin page (lines + transcription, sort/filter, notifications with badge, articles, users, zones, CSV export, close inventory) | ✅ built, tested in browser |
| Backup to NAS (built in, off until `backup_cartella` is set) | ✅ built, not tested (no NAS folder yet) |
| Automatic deletion of old transcripts | ✅ built |
| Built-in number pad on the operator page (system keyboard still opens for now) | ⬜ |
| Test on a real tablet/phone (microphone permission, certificate) | ⬜ |
| Production PC setup (Windows service, firewall, fixed IP) | ⬜ RTX to confirm, deploy later |

## 15. Decisions

**Taken**

| Topic | Decision |
|---|---|
| Altervista | Not used any more; contains nothing useful and is not connected to the server → left as it is. |
| Database | SQLite on the PC. |
| Login on the tablets | Name chosen from the user list + 4-digit PIN. Admin with a password. |
| Who can change what | Each person only their own lines; admin everything. |
| Closing the inventory | Admin button: "Archivia con data" (kept, tagged with the date) or "Cancella". |
| Final output | For now a CSV with totals per article. Later: comparison with the CRM stock (discrepancies). |
| Article maintenance | By hand from the admin screen, after a one-time import from Altervista. |
| New articles | Admin only; staff use "Segnala articolo mancante". |
| Possible duplicates | Flagged in admin notifications that stay until marked handled. |
| Backups | Built in now, switched on once the NAS folder is known. |
| Audio | Never kept. Transcripts kept, deleted after a set time (§13). |
| Access from outside | None. |
| Tablets | Designed for a generic tablet / phone (iPad, Android); first tests from a phone. |
| PC | Core Ultra + RTX, 8 GB VRAM (to confirm). |

**Still open**

| Topic | When |
|---|---|
| Units per field, required fields per unit, spoken section order, trasversali, measures from the CRM | At the company — [dati/README.md](dati/README.md) |
| Transcript retention (90 days proposed) and the information notice | With the privacy / labour consultant |
| Columns of the CRM comparison | When the CRM export format is known |
| NAS backup folder | At the company |
| Tablet models | At the company |
| Keep or drop Qwen | After testing on the real catalog |

## 16. Files

| Path | What |
|---|---|
| `server.py` | Starts everything: HTTPS, certificates, backups, transcript cleanup |
| `api.py` | Pages and API: login, lines, admin, export |
| `db.py` | SQLite database, first-start import, `python db.py reset-admin` |
| `trascrizione.py` | Whisper, portable, load/unload |
| `inventario.py` | Text → article + fields (rules, units, Qwen when unsure) |
| `ricerca.py` | Article search over the catalog |
| `misure_auto.py` | Measures read from article descriptions |
| `catalogo.py` | Reads `dati/` (articles CSV, measures, rules) |
| `controlla_dati.py` | Reports what is still missing in `dati/` |
| `static/` | Pages: `login.html`, `operatore.html/.js`, `admin.html/.js`, `stile.css`, `comune.js`, `sw.js` (offline) |
| `config.py`, `config.example.json` | Settings |
| `dati/` | **Company data** — see `dati/README.md` (`articoli.csv` is not in git) |
| `inventario.db` | The database (created at first start, not in git) |

Old files (Altervista site, NAS assistant experiments, test audio) were moved to the folder
`Riconoscimento vocale - archivio` on the Desktop.

## 17. Running it

```bash
python3.12 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python server.py
```

At the first start it imports `dati/articoli.csv` and prints the **admin password** once (lost? `venv/bin/python
db.py reset-admin`). Then open `https://<PC address>:8000` — the admin creates the users from the Utenti tab.
On Windows the paths are `venv\Scripts\python` and `venv\Scripts\pip`.
