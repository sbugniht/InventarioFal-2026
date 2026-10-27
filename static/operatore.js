// Pagina di chi fa l'inventario.
// Il pulsante grande ha tre fasi: Registra -> Ferma -> Salva. Finché una riga non è salvata
// (o scartata) non se ne può registrare un'altra.
// Ogni riga salvata va prima nella coda del tablet e poi al server: se manca la rete aspetta.

const CAMPI = ["pezzi", "spessore", "larghezza", "lunghezza", "trasversali"];
const NOMI_CAMPI = { pezzi: "Pezzi", spessore: "Spessore", larghezza: "Larghezza", lunghezza: "Lunghezza", trasversali: "Trasversali" };

const s = {
  fase: "pronto",          // pronto | registra | attesa | verifica
  registratore: null,
  articolo: null,
  detti: null,             // valori detti a voce (con unità), per ricalcolare se si cambia articolo
  trascrizione: "",
  metodo: "manuale",
  candidati: [],
  daCatalogo: new Set(),   // campi riempiti dal catalogo (non detti né scritti)
  modifica: null,          // id della riga in modifica
  mostraTutti: false,
  io: memoria.leggi("io"),
};
let catalogo = memoria.leggi("catalogo", { articoli: [], zone: [], regole: { unita: {}, salvataggio: {} } });
let articoliPerId = new Map(catalogo.articoli.map(a => [a.id, a]));

// --- Avvio ---------------------------------------------------------------------
async function avvio() {
  try {
    s.io = await api("/api/io");
    memoria.scrivi("io", s.io);
  } catch (e) {
    if (e.stato !== 0 || !s.io) { location.href = "/login"; return; }
  }
  $("#nome").textContent = s.io.nome;
  try {
    catalogo = await api("/api/catalogo");
    memoria.scrivi("catalogo", catalogo);
    articoliPerId = new Map(catalogo.articoli.map(a => [a.id, a]));
  } catch { /* senza rete uso la copia salvata */ }
  riempiZone();
  aggiornaCoda();
  inviaCoda();
  aggiornaOggi();
}

// --- Zona: elenco per area + mappa (mappa.js) -----------------------------------------
// Il <select id="zona"> nascosto tiene il valore (lo leggono il salvataggio e la voce);
// l'elenco e la mappa lo cambiano tramite impostaZona.
let mappa = null;

function riempiZone() {
  const attuale = memoria.leggi("zona");
  $("#zona").innerHTML = `<option value="">—</option>` +
    catalogo.zone.map(z => `<option value="${z.id}">${esc(z.nome)}</option>`).join("");
  $("#zona").value = attuale && catalogo.zone.some(z => z.id === attuale) ? String(attuale) : "";
  const aree = catalogo.aree || [];
  // Raggruppate per area, nell'ordine delle aree; poi quelle senza area
  const gruppi = [...aree.map(ar => [ar.nome, catalogo.zone.filter(z => z.area_id === ar.id)]),
                  [aree.length ? "Altre zone" : "", catalogo.zone.filter(z => !aree.some(ar => ar.id === z.area_id))]]
    .filter(([, zone]) => zone.length);
  $("#zona-tendina").innerHTML = `<button role="option" data-zona="">— nessuna zona</button>` +
    gruppi.map(([nome, zone]) => (nome ? `<div class="gruppo">${esc(nome)}</div>` : "") + zone.map(z =>
      `<button role="option" data-zona="${z.id}"><span class="pallino" style="background:${esc(coloreZona(z))}"></span>${esc(z.nome)}</button>`
    ).join("")).join("");
  if (catalogo.mappa) {
    $("#scheda-mappa").classList.remove("nascosto");
    if (mappa) mappa.aggiorna(aree, catalogo.zone);
    else mappa = new Mappa($("#mappa-operatore"), { info: catalogo.mappa, aree, zone: catalogo.zone,
                                                    scegliZona: id => impostaZona(id) });
  }
  mostraZona();
}
function mostraZona() {
  const id = Number($("#zona").value) || null;
  const z = catalogo.zone.find(z => z.id === id);
  $("#zona-bottone").textContent = `Zona: ${z ? z.nome : "—"} ▾`;
  document.querySelectorAll("#zona-tendina button").forEach(b => b.classList.toggle("scelta", Number(b.dataset.zona) === id));
  mappa?.scegli(id);
}
function impostaZona(id) {
  $("#zona").value = id ? String(id) : "";
  memoria.scrivi("zona", id || null);
  mostraZona();
}

function apriTendina(aperta) {
  $("#zona-tendina").classList.toggle("nascosto", !aperta);
  $("#zona-bottone").setAttribute("aria-expanded", aperta);
  if (!aperta) mappa?.accendi(null);
}
$("#zona-bottone").addEventListener("click", () => apriTendina($("#zona-tendina").classList.contains("nascosto")));
$("#zona-tendina").addEventListener("click", e => {
  const b = e.target.closest("button[data-zona]");
  if (!b) return;
  impostaZona(Number(b.dataset.zona) || null);
  apriTendina(false);
});
// Passando sopra a una voce (PC) la zona si accende sulla mappa; sul tablet si accende quando la si sceglie
$("#zona-tendina").addEventListener("pointerover", e => {
  const b = e.target.closest("button[data-zona]");
  if (b && e.pointerType === "mouse") mappa?.accendi(Number(b.dataset.zona) || null);
});
$("#zona-tendina").addEventListener("pointerleave", () => mappa?.accendi(null));
document.addEventListener("click", e => { if (!e.target.closest(".scelta-zona")) apriTendina(false); });
document.addEventListener("keydown", e => { if (e.key === "Escape") apriTendina(false); });

// --- Il pulsante grande ----------------------------------------------------------
function fase(nuova, messaggio) {
  s.fase = nuova;
  const b = $("#grande");
  b.classList.toggle("registra", nuova === "registra");
  b.classList.toggle("attesa", nuova === "attesa");
  b.disabled = nuova === "attesa";
  b.textContent = { pronto: "🎤 Registra", registra: "⏹ Ferma", attesa: "Analisi…", verifica: "✓ Salva" }[nuova];
  $("#azioni-pronto").classList.toggle("nascosto", nuova !== "pronto");
  $("#verifica").classList.toggle("nascosto", nuova !== "verifica");
  if (messaggio !== undefined) $("#stato").textContent = messaggio;
}

$("#grande").addEventListener("click", () => {
  if (s.fase === "pronto") avviaRegistrazione();
  else if (s.fase === "registra") fermaRegistrazione();
  else if (s.fase === "verifica") salva();
});

async function avviaRegistrazione() {
  beep("ok"); // sblocca l'audio sui tablet (serve un tocco dell'utente)
  let flusso;
  try {
    flusso = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    fase("pronto", "Microfono non disponibile: controlla i permessi del browser, oppure inserisci a mano.");
    return;
  }
  const tipo = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
  const pezzi = [];
  s.registratore = new MediaRecorder(flusso, tipo ? { mimeType: tipo } : undefined);
  s.registratore.ondataavailable = e => e.data.size && pezzi.push(e.data);
  s.registratore.onstop = () => {
    flusso.getTracks().forEach(t => t.stop());
    const mime = s.registratore.mimeType || tipo || "audio/webm";
    inviaAudio(new Blob(pezzi, { type: mime }), mime.includes("mp4") ? ".m4a" : ".webm");
  };
  s.registratore.start();
  fase("registra", "Sto ascoltando… premi Ferma quando hai finito.");
}

function fermaRegistrazione() {
  fase("attesa", "Sto capendo cosa hai detto…");
  s.registratore.stop();
}

async function inviaAudio(blob, estensione) {
  const fd = new FormData();
  fd.append("audio", blob, "registrazione" + estensione);
  try {
    const r = await api("/api/voce", { method: "POST", body: fd });
    mostraRisultato(r);
  } catch (e) {
    if (e.stato === 0) {
      // Senza rete niente trascrizione: si continua a mano e la riga aspetta nella coda
      apriManuale("Nessuna connessione: inserisci la riga a mano. Verrà inviata appena torna la rete.");
    } else {
      beep("errore");
      fase("pronto", e.message);
    }
  }
}

// --- Verifica della riga ---------------------------------------------------------
function nuovaVerifica() {
  s.articolo = null; s.detti = null; s.trascrizione = ""; s.metodo = "manuale";
  s.candidati = []; s.daCatalogo = new Set(); s.modifica = null; s.mostraTutti = false;
  $("#note").value = "";
  $("#cerca").value = "";
  $("#risultati").innerHTML = "";
  $("#avviso").classList.add("nascosto");
  $("#conversioni").classList.add("nascosto");
  $("#trascrizione").classList.add("nascosto");
  $("#ricerca").classList.add("nascosto");
  CAMPI.forEach(c => s[c] = null);
}

function mostraRisultato(r) {
  nuovaVerifica();
  s.trascrizione = r.testo;
  s.metodo = r.metodo;
  s.detti = r.detti;
  s.candidati = r.candidati;
  $("#trascrizione").textContent = `«${r.testo}»`;
  $("#trascrizione").classList.remove("nascosto");
  if (r.zona) impostaZona(r.zona.id);
  $("#note").value = r.note || "";
  if (r.conversioni && r.conversioni.length) {
    $("#conversioni").textContent = "Convertito: " + r.conversioni.join(" · ");
    $("#conversioni").classList.remove("nascosto");
  }
  if (!r.scelto) {
    mostraAvviso("Non ho trovato l'articolo: cercalo qui sotto.");
    apriRicerca(r.testo);
  } else if (r.metodo === "voce:incerto") {
    mostraAvviso("Non sono sicuro dell'articolo: controlla o tocca un'alternativa.");
  }
  if (r.avviso) console.warn(r.avviso);
  s.articolo = articoliPerId.get(r.scelto) || r.candidati.find(c => c.id === r.scelto) || null;
  if (r.campi) {
    CAMPI.forEach(c => s[c] = r.campi[c]);
    s.daCatalogo = new Set(r.da_catalogo || []);
  }
  fase("verifica", "Controlla e premi Salva.");
  disegna();
}

function apriManuale(avviso) {
  nuovaVerifica();
  if (avviso) mostraAvviso(avviso);
  fase("verifica", "Scegli l'articolo e scrivi le quantità, poi premi Salva.");
  disegna();
  apriRicerca("");
}

function mostraAvviso(testo) {
  $("#avviso").textContent = testo;
  $("#avviso").classList.remove("nascosto");
}

$("#manuale").addEventListener("click", () => apriManuale());

$("#scarta").addEventListener("click", () => {
  const domanda = s.modifica ? "Annullare la modifica?" : "Scartare questa riga senza salvarla?";
  if (confirm(domanda)) { nuovaVerifica(); fase("pronto", "Riga scartata."); }
});

// Regole dell'unità dell'articolo (campi obbligatori, etichette, totale)
function regola(articolo) {
  const u = catalogo.regole.unita || {};
  return (articolo && (u[articolo.unita] || u["Pz"])) || { obbligatori: ["pezzi"] };
}

function disegna() {
  // Articolo scelto e alternative
  const a = s.articolo;
  $("#articolo-scelto").innerHTML = a
    ? `<div class="articolo"><div class="codice">${esc(a.codice)} <span class="tenue">· ${esc(a.unita)}</span></div><div>${esc(a.descrizione)}</div></div>`
    : `<div class="avviso">Nessun articolo scelto</div>`;
  const altri = s.candidati.filter(c => !a || c.id !== a.id).slice(0, 4);
  $("#alternative").innerHTML = altri.map(c =>
    `<button class="alternativa" data-id="${c.id}"><b>${esc(c.codice)}</b> ${esc(c.descrizione)}</button>`).join("");

  // Campi: obbligatori e già compilati sempre visibili, gli altri dietro "+ altre misure"
  const r = regola(a);
  const sal = catalogo.regole.salvataggio || {};
  let nascosti = 0;
  $("#campi").innerHTML = CAMPI.map(c => {
    const obbligatorio = r.obbligatori.includes(c);
    const visibile = obbligatorio || s[c] !== null || s.mostraTutti;
    if (!visibile) { nascosti++; return ""; }
    const etichetta = c === "pezzi" ? (r.etichetta_pezzi || "Pezzi") : `${NOMI_CAMPI[c]} (${sal[c] || ""})`;
    const origine = s.daCatalogo.has(c)
      ? `<div class="origine">dal catalogo${a && a.misure_auto ? " · da verificare" : ""}</div>` : "";
    return `<div class="campo ${obbligatorio ? "obbligatorio" : ""} ${obbligatorio && s[c] === null ? "mancante" : ""}">
      <label for="campo-${c}">${esc(etichetta)}${obbligatorio ? " *" : ""}</label>
      <input type="text" inputmode="decimal" id="campo-${c}" data-campo="${c}" value="${formatoNumero(s[c])}" autocomplete="off">
      ${origine}</div>`;
  }).join("");
  $("#altre-misure").classList.toggle("nascosto", nascosti === 0);
  aggiornaTotale();
}

$("#campi").addEventListener("input", e => {
  const c = e.target.dataset.campo;
  if (!c) return;
  const n = leggiNumero(e.target.value);
  s[c] = Number.isNaN(n) ? null : n;
  s.daCatalogo.delete(c);
  e.target.closest(".campo").classList.toggle("mancante", e.target.closest(".obbligatorio") && n === null);
  aggiornaTotale();
});

$("#altre-misure").addEventListener("click", () => { s.mostraTutti = true; disegna(); });

function aggiornaTotale() {
  const r = regola(s.articolo);
  if (!r.totale || !s.articolo) { $("#totale").textContent = ""; return; }
  const usati = CAMPI.filter(c => r.totale.includes(c));
  if (usati.some(c => s[c] === null)) { $("#totale").textContent = ""; return; }
  try {
    // Formula da dati/regole_unita.json (es. "pezzi * spessore/1000 * larghezza/100 * lunghezza")
    const valore = new Function(...CAMPI, `return ${r.totale};`)(...CAMPI.map(c => s[c] ?? 0));
    const unita = { Ml: "m", Mq: "m²", Mc: "m³" }[s.articolo.unita] || "";
    $("#totale").textContent = `Totale: ${formatoNumero(Math.round(valore * 10000) / 10000)} ${unita}`;
  } catch { $("#totale").textContent = ""; }
}

// --- Scelta dell'articolo -----------------------------------------------------------
async function scegliArticolo(articolo) {
  s.articolo = articolo;
  $("#ricerca").classList.add("nascosto");
  $("#avviso").classList.add("nascosto");
  if (s.metodo.startsWith("voce")) s.metodo = "voce:scelta";
  // Le misure prese dal catalogo del vecchio articolo non valgono più
  s.daCatalogo.forEach(c => s[c] = null);
  s.daCatalogo = new Set();
  if (s.detti) {
    try {
      // Ricalcolo lato server: unità dette e unità tipiche del nuovo articolo
      const r = await api("/api/applica", { json: { articolo_id: articolo.id, detti: s.detti } });
      CAMPI.forEach(c => { if (r.campi[c] !== null) s[c] = r.campi[c]; });
      s.daCatalogo = new Set(r.da_catalogo);
      return disegna();
    } catch { /* senza rete: solo le misure fisse */ }
  }
  ["spessore", "larghezza", "lunghezza", "trasversali"].forEach(c => {
    if (s[c] === null && articolo[c] !== null && articolo[c] !== undefined) { s[c] = articolo[c]; s.daCatalogo.add(c); }
  });
  disegna();
}

$("#alternative").addEventListener("click", e => {
  const b = e.target.closest("button[data-id]");
  if (!b) return;
  const id = Number(b.dataset.id);
  scegliArticolo(articoliPerId.get(id) || s.candidati.find(c => c.id === id));
});

function apriRicerca(testo) {
  $("#ricerca").classList.remove("nascosto");
  $("#cerca").value = testo || "";
  cerca();
  $("#cerca").focus();
}
$("#cambia-articolo").addEventListener("click", () => apriRicerca(""));

function cerca() {
  const parole = $("#cerca").value.toLowerCase().split(/\s+/).filter(Boolean);
  if (!parole.length) { $("#risultati").innerHTML = ""; return; }
  const trovati = [];
  for (const a of catalogo.articoli) {
    const testo = (a.codice + " " + a.descrizione).toLowerCase();
    if (parole.every(p => testo.includes(p))) trovati.push(a);
    if (trovati.length >= 30) break;
  }
  $("#risultati").innerHTML = trovati.length
    ? trovati.map(a => `<button class="alternativa" data-id="${a.id}"><b>${esc(a.codice)}</b> ${esc(a.descrizione)} <span class="tenue">· ${esc(a.unita)}</span></button>`).join("")
    : `<span class="tenue">Nessun articolo. Se manca dal catalogo usa "Articolo mancante?".</span>`;
}
$("#cerca").addEventListener("input", cerca);
$("#risultati").addEventListener("click", e => {
  const b = e.target.closest("button[data-id]");
  if (b) scegliArticolo(articoliPerId.get(Number(b.dataset.id)));
});

// --- Salvataggio --------------------------------------------------------------------
async function salva() {
  if (!s.articolo) {
    beep("errore"); lampo("Scegli l'articolo", true); apriRicerca(""); return;
  }
  const sbagliati = [...document.querySelectorAll("#campi input")].filter(i => Number.isNaN(leggiNumero(i.value)));
  if (sbagliati.length) {
    beep("errore"); lampo("Numero non valido", true); sbagliati[0].focus(); return;
  }
  const mancanti = regola(s.articolo).obbligatori.filter(c => s[c] === null);
  if (mancanti.length) {
    beep("errore");
    lampo("Manca: " + mancanti.map(c => NOMI_CAMPI[c].toLowerCase()).join(", "), true);
    disegna();
    return;
  }
  const riga = {
    articolo_id: s.articolo.id,
    note: $("#note").value.trim(),
    zona_id: Number($("#zona").value) || null,
    ...Object.fromEntries(CAMPI.map(c => [c, s[c]])),
  };
  const descrizione = `${s.articolo.codice} · ${formatoNumero(s.pezzi)} ${s.articolo.unita === "Pz" || !s.articolo.unita ? "pz" : "pezzi"}`;

  if (s.modifica) {
    try {
      await api(`/api/righe/${encodeURIComponent(s.modifica)}`, { method: "PUT", json: riga });
    } catch (e) {
      beep("errore");
      lampo(e.stato === 0 ? "Serve la rete per modificare una riga già inviata" : e.message, true);
      return;
    }
  } else {
    // Prima nella coda del tablet, poi al server: niente si perde se cade la rete
    const coda = memoria.leggi("coda", []);
    coda.push({ ...riga, id: idUnivoco(), utente_id: s.io.id, trascrizione: s.trascrizione || null,
                metodo: s.metodo, creata: adessoLocale(), offline: false,
                _etichetta: `${s.articolo.codice} ${s.articolo.descrizione}` });
    memoria.scrivi("coda", coda);
    inviaCoda();
  }
  beep("ok");
  lampo("✓ Salvato\n" + descrizione);
  nuovaVerifica();
  fase("pronto", `Ultima riga salvata: ${descrizione}`);
  aggiornaOggi();
}

// --- Coda delle righe da inviare ------------------------------------------------------
let invioInCorso = false;
async function inviaCoda() {
  if (invioInCorso) return;
  invioInCorso = true;
  try {
    let coda = memoria.leggi("coda", []);
    for (const riga of [...coda]) {
      if (riga.utente_id !== s.io.id || riga.errore) continue; // righe di un altro utente: aspettano il suo accesso
      const { _etichetta, utente_id, errore, ...dati } = riga;
      try {
        await api("/api/righe", { json: dati });
        coda = memoria.leggi("coda", []).filter(r => r.id !== riga.id);
      } catch (e) {
        coda = memoria.leggi("coda", []);
        const voce = coda.find(r => r.id === riga.id);
        if (e.stato === 0) { if (voce) voce.offline = true; memoria.scrivi("coda", coda); break; }
        if (voce) voce.errore = e.message; // dati rifiutati: resta visibile per correggerla o eliminarla
      }
      memoria.scrivi("coda", coda);
    }
  } finally {
    invioInCorso = false;
    aggiornaCoda();
    aggiornaOggi();
  }
}

function aggiornaCoda() {
  const n = memoria.leggi("coda", []).filter(r => r.utente_id === (s.io && s.io.id)).length;
  $("#coda").textContent = n ? `⏳ ${n} in attesa` : "✓ inviato";
  $("#coda").classList.toggle("attesa", n > 0);
  $("#coda").classList.toggle("ok", n === 0);
}

setInterval(inviaCoda, 15000);
window.addEventListener("online", inviaCoda);

// --- Righe di oggi (o di tutti i giorni dell'inventario in corso) ------------------------
let tutteLeRighe = memoria.leggi("tutte_le_righe", false);
function mostraPeriodo() {
  $("#periodo").textContent = tutteLeRighe ? "📅 Tutti i giorni" : "📅 Oggi";
  $("#titolo-righe").textContent = tutteLeRighe ? "Le tue righe di tutti i giorni" : "Le tue righe di oggi";
}
mostraPeriodo();
$("#periodo").addEventListener("click", () => {
  tutteLeRighe = !tutteLeRighe;
  memoria.scrivi("tutte_le_righe", tutteLeRighe);
  mostraPeriodo();
  aggiornaOggi();
});

async function aggiornaOggi() {
  const tutte = tutteLeRighe, chiave = tutte ? "tutte" : "oggi";
  let righe = memoria.leggi(chiave, []);
  try {
    righe = await api("/api/righe/mie" + (tutte ? "?tutte=1" : ""));
    memoria.scrivi(chiave, righe);
  } catch { /* senza rete: ultima copia */ }
  if (tutte !== tutteLeRighe) return;  // nel frattempo si è cambiato periodo
  // Di tutti i giorni serve anche la data: "27/10 14:32"
  const quando = c => (tutte ? `${c.slice(8, 10)}/${c.slice(5, 7)} ` : "") + c.slice(11, 16);
  const inAttesa = memoria.leggi("coda", []).filter(r => r.utente_id === s.io.id);
  const html = [
    ...inAttesa.map(r => `<div class="riga-elenco">
      <div class="testo"><span class="etichetta">${r.errore ? "errore: " + esc(r.errore) : "in attesa"}</span>
        ${esc(quando(r.creata))} <b>${esc(r._etichetta || "")}</b><br>${riassunto(r)}</div>
      <button class="btn piccolo pericolo" data-elimina-coda="${esc(r.id)}">Elimina</button></div>`),
    ...righe.map(r => `<div class="riga-elenco">
      <div class="testo">${esc(quando(r.creata))} <b>${esc(r.codice)}</b> ${esc(r.descrizione)}<br>${riassunto(r)}${r.zona ? " · " + esc(r.zona) : ""}</div>
      <button class="btn piccolo" data-modifica="${esc(r.id)}">Modifica</button>
      <button class="btn piccolo pericolo" data-elimina="${esc(r.id)}">Elimina</button></div>`),
  ];
  $("#oggi").innerHTML = html.join("") || `<span class="tenue">Nessuna riga.</span>`;
}

function riassunto(r) {
  const parti = [];
  if (r.pezzi !== null) parti.push(`${formatoNumero(r.pezzi)} pz`);
  const misure = ["spessore", "larghezza", "lunghezza"].filter(c => r[c] !== null).map(c => formatoNumero(r[c]));
  if (misure.length) parti.push(misure.join(" × "));
  if (quantita(r)) parti.push(`<b>= ${quantita(r)}</b>`);
  if (r.note) parti.push(esc(r.note));
  return `<span class="tenue">${parti.join(" · ")}</span>`;
}

$("#oggi").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.eliminaCoda) {
    if (!confirm("Eliminare questa riga non ancora inviata?")) return;
    memoria.scrivi("coda", memoria.leggi("coda", []).filter(r => r.id !== b.dataset.eliminaCoda));
    aggiornaCoda(); aggiornaOggi();
  } else if (b.dataset.elimina) {
    if (!confirm("Eliminare questa riga?")) return;
    try { await api(`/api/righe/${encodeURIComponent(b.dataset.elimina)}`, { method: "DELETE" }); }
    catch (err) { lampo(err.message, true); }
    aggiornaOggi();
  } else if (b.dataset.modifica) {
    if (s.fase !== "pronto") { lampo("Prima salva o scarta la riga in corso", true); return; }
    const r = memoria.leggi(tutteLeRighe ? "tutte" : "oggi", []).find(x => x.id === b.dataset.modifica);
    if (!r) return;
    nuovaVerifica();
    s.modifica = r.id;
    s.articolo = articoliPerId.get(r.articolo_id) || { id: r.articolo_id, codice: r.codice, descrizione: r.descrizione, unita: r.unita };
    CAMPI.forEach(c => s[c] = r[c]);
    $("#note").value = r.note || "";
    impostaZona(r.zona_id);
    fase("verifica", "Modifica la riga e premi Salva.");
    disegna();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
});

// --- Articolo mancante -------------------------------------------------------------------
$("#segnala").addEventListener("click", () => { $("#errore-segnala").textContent = ""; $("#dialogo-segnala").showModal(); });
$("#chiudi-segnala").addEventListener("click", () => $("#dialogo-segnala").close());
$("#invia-segnala").addEventListener("click", async () => {
  try {
    await api("/api/segnalazioni", { json: { testo: $("#testo-segnala").value } });
    $("#testo-segnala").value = "";
    $("#dialogo-segnala").close();
    beep("ok"); lampo("Segnalazione inviata all'admin");
  } catch (e) { $("#errore-segnala").textContent = e.message; }
});

// --- Uscita ------------------------------------------------------------------------------
$("#esci").addEventListener("click", async () => {
  await inviaCoda();
  const n = memoria.leggi("coda", []).filter(r => r.utente_id === s.io.id).length;
  if (n) { alert(`Ci sono ${n} righe non ancora inviate. Esci quando torna la rete, così non si perdono.`); return; }
  if (s.fase === "verifica" && !confirm("C'è una riga non salvata: uscire lo stesso?")) return;
  try { await api("/api/uscita", { method: "POST" }); } catch { /* pazienza */ }
  memoria.scrivi("io", null);
  location.href = "/login";
});

fase("pronto");
avvio();
