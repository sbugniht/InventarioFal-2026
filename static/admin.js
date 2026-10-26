// Pagina dell'admin. Resta aperta in background: le notifiche si aggiornano da sole e il numero
// di quelle da controllare compare anche nel titolo della scheda del browser.

const CAMPI = ["pezzi", "spessore", "larghezza", "lunghezza", "trasversali"];
const ETICHETTE = { pezzi: "Pezzi", spessore: "Spessore (mm)", larghezza: "Larghezza (cm)", lunghezza: "Lunghezza (m)", trasversali: "Trasversali (m)" };
const a = { righe: [], ordina: "creata", verso: "desc", zone: [], utenti: [], rigaAperta: null, articoloAperto: null };

// --- Schede --------------------------------------------------------------------
$("#schede").addEventListener("click", e => {
  const b = e.target.closest("button[data-scheda]");
  if (!b) return;
  document.querySelectorAll("#schede button").forEach(x => x.classList.toggle("attiva", x === b));
  document.querySelectorAll("main > section").forEach(sez => sez.classList.toggle("nascosto", sez.id !== "scheda-" + b.dataset.scheda));
  ({ righe: caricaRighe, notifiche: caricaNotifiche, articoli: caricaArticoli, utenti: caricaUtenti, zone: caricaZone }[b.dataset.scheda] || (() => {}))();
});

// --- Stato generale e notifiche -------------------------------------------------
async function aggiornaStato() {
  try {
    const st = await api("/api/admin/stato");
    $("#badge").textContent = st.notifiche;
    $("#badge").classList.toggle("nascosto", st.notifiche === 0);
    $("#conteggio-righe").textContent = `${st.righe} righe nell'inventario in corso`;
    document.title = (st.notifiche ? `(${st.notifiche}) ` : "") + "Inventario · Admin";
  } catch { /* riprova al prossimo giro */ }
}
setInterval(() => {
  aggiornaStato();
  if (!$("#scheda-righe").classList.contains("nascosto")) caricaRighe();
  if (!$("#scheda-notifiche").classList.contains("nascosto")) caricaNotifiche();
}, 20000);

async function caricaNotifiche() {
  const tutte = $("#mostra-gestite").checked ? "?tutte=1" : "";
  const elenco = await api("/api/admin/notifiche" + tutte);
  $("#notifiche").innerHTML = elenco.map(n => `<div class="riga-elenco">
      <div class="testo"><span class="etichetta">${n.tipo === "doppione" ? "possibile doppione" : "articolo mancante"}</span>
        ${esc(n.creata.replace("T", " ").slice(0, 16))}<br>${esc(n.testo)}
        ${n.gestita_il ? `<br><span class="tenue">gestita il ${esc(n.gestita_il.replace("T", " ").slice(0, 16))}</span>` : ""}</div>
      ${n.riga_id ? `<button class="btn piccolo" data-apri-riga="${esc(n.riga_id)}">Vedi riga</button>` : ""}
      ${n.gestita_il ? "" : `<button class="btn piccolo primario" data-gestita="${n.id}">Gestita</button>`}
    </div>`).join("") || `<span class="tenue">Niente da controllare.</span>`;
}
$("#mostra-gestite").addEventListener("change", caricaNotifiche);
$("#notifiche").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.gestita) {
    await api(`/api/admin/notifiche/${b.dataset.gestita}`, { method: "POST" });
    caricaNotifiche(); aggiornaStato();
  } else if (b.dataset.apriRiga) {
    await caricaRighe();
    const r = a.righe.find(x => x.id === b.dataset.apriRiga);
    if (r) apriRiga(r); else alert("La riga è stata eliminata.");
  }
});

// --- Inventario in corso ----------------------------------------------------------
async function caricaFiltri() {
  [a.utenti, a.zone] = await Promise.all([api("/api/admin/utenti"), api("/api/admin/zone")]);
  const fu = $("#filtro-utente").value, fz = $("#filtro-zona").value;
  $("#filtro-utente").innerHTML = `<option value="">Tutti gli utenti</option>` + a.utenti.map(u => `<option value="${u.id}">${esc(u.nome)}</option>`).join("");
  $("#filtro-zona").innerHTML = `<option value="">Tutte le zone</option>` + a.zone.map(z => `<option value="${z.id}">${esc(z.nome)}</option>`).join("");
  $("#filtro-utente").value = fu; $("#filtro-zona").value = fz;
}

async function caricaRighe() {
  const p = new URLSearchParams({ ordina: a.ordina, verso: a.verso, cerca: $("#filtro-cerca").value,
                                  utente: $("#filtro-utente").value, zona: $("#filtro-zona").value });
  a.righe = await api("/api/admin/righe?" + p);
  $("#righe").innerHTML = a.righe.map(r => `<tr data-id="${esc(r.id)}">
      <td>${esc(r.creata.replace("T", " ").slice(0, 16))}${r.offline ? ' <span class="etichetta" title="Salvata senza rete">offline</span>' : ""}</td>
      <td>${esc(r.utente)}</td><td>${esc(r.zona || "")}</td>
      <td><b>${esc(r.codice)}</b> ${esc(r.descrizione)}</td>
      ${CAMPI.map(c => `<td class="num">${formatoNumero(r[c])}</td>`).join("")}
      <td>${esc(r.note)}</td></tr>`).join("") || `<tr><td colspan="10" class="tenue">Nessuna riga.</td></tr>`;
  document.querySelectorAll("th[data-ordina]").forEach(th => {
    th.textContent = th.textContent.replace(/ [▴▾]$/, "") + (th.dataset.ordina === a.ordina ? (a.verso === "asc" ? " ▴" : " ▾") : "");
  });
}
document.querySelectorAll("th[data-ordina]").forEach(th => th.addEventListener("click", () => {
  a.verso = a.ordina === th.dataset.ordina && a.verso === "desc" ? "asc" : "desc";
  a.ordina = th.dataset.ordina;
  caricaRighe();
}));
let attesaCerca;
$("#filtro-cerca").addEventListener("input", () => { clearTimeout(attesaCerca); attesaCerca = setTimeout(caricaRighe, 300); });
$("#filtro-utente").addEventListener("change", caricaRighe);
$("#filtro-zona").addEventListener("change", caricaRighe);
$("#righe").addEventListener("click", e => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) apriRiga(a.righe.find(r => r.id === tr.dataset.id));
});

function apriRiga(r) {
  a.rigaAperta = r;
  $("#riga-titolo").textContent = `${r.codice} · ${r.descrizione}`;
  $("#riga-trascrizione").textContent = r.trascrizione ? `«${r.trascrizione}»` : "Inserita a mano (nessuna trascrizione).";
  $("#riga-info").textContent = `${r.utente} · ${r.creata.replace("T", " ")} · metodo: ${r.metodo}` +
    (r.offline ? " · salvata senza rete" : "") + (r.modificata ? ` · modificata il ${r.modificata.replace("T", " ")}` : "");
  $("#riga-campi").innerHTML = CAMPI.map(c => `<div><label for="riga-${c}">${ETICHETTE[c]}</label>
    <input type="text" inputmode="decimal" id="riga-${c}" value="${formatoNumero(r[c])}"></div>`).join("");
  $("#riga-note").value = r.note || "";
  $("#riga-zona").innerHTML = `<option value="">—</option>` + a.zone.map(z => `<option value="${z.id}">${esc(z.nome)}</option>`).join("");
  $("#riga-zona").value = r.zona_id || "";
  $("#riga-errore").textContent = "";
  $("#dialogo-riga").showModal();
}
$("#riga-chiudi").addEventListener("click", () => $("#dialogo-riga").close());
$("#riga-salva").addEventListener("click", async () => {
  const dati = { articolo_id: a.rigaAperta.articolo_id, note: $("#riga-note").value, zona_id: Number($("#riga-zona").value) || null };
  for (const c of CAMPI) {
    const n = leggiNumero($(`#riga-${c}`).value);
    if (Number.isNaN(n)) { $("#riga-errore").textContent = `${ETICHETTE[c]}: numero non valido`; return; }
    dati[c] = n;
  }
  try {
    await api(`/api/righe/${encodeURIComponent(a.rigaAperta.id)}`, { method: "PUT", json: dati });
    $("#dialogo-riga").close(); caricaRighe();
  } catch (e) { $("#riga-errore").textContent = e.message; }
});
$("#riga-elimina").addEventListener("click", async () => {
  if (!confirm("Eliminare questa riga?")) return;
  await api(`/api/righe/${encodeURIComponent(a.rigaAperta.id)}`, { method: "DELETE" });
  $("#dialogo-riga").close(); caricaRighe(); aggiornaStato();
});

// --- Articoli ------------------------------------------------------------------------
let articoli = [];
async function caricaArticoli() {
  articoli = await api("/api/admin/articoli?cerca=" + encodeURIComponent($("#cerca-articoli").value));
  $("#articoli").innerHTML = articoli.map(r => `<tr data-id="${r.id}">
      <td><b>${esc(r.codice)}</b></td><td>${esc(r.descrizione)}</td><td>${esc(r.unita)}</td>
      ${["spessore", "larghezza", "lunghezza", "trasversali"].map(c => `<td class="num">${formatoNumero(r[c])}</td>`).join("")}
      <td>${r.misure_auto ? '<span class="etichetta">auto</span> ' : ""}${r.attivo ? "" : '<span class="tenue">disattivo</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="8" class="tenue">Nessun articolo.</td></tr>`;
}
let attesaArticoli;
$("#cerca-articoli").addEventListener("input", () => { clearTimeout(attesaArticoli); attesaArticoli = setTimeout(caricaArticoli, 300); });
$("#articoli").addEventListener("click", e => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) apriArticolo(articoli.find(r => r.id === Number(tr.dataset.id)));
});
$("#nuovo-articolo").addEventListener("click", () => apriArticolo(null));

function apriArticolo(r) {
  a.articoloAperto = r;
  $("#articolo-titolo").textContent = r ? `Articolo ${r.codice}` : "Nuovo articolo";
  $("#art-codice").value = r ? r.codice : "";
  $("#art-unita").value = r ? r.unita : "Pz";
  $("#art-descrizione").value = r ? r.descrizione : "";
  ["spessore", "larghezza", "lunghezza", "trasversali"].forEach(c => $(`#art-${c}`).value = r ? formatoNumero(r[c]) : "");
  $("#art-verificate").checked = !r || !r.misure_auto;
  $("#art-sinonimi").value = r ? r.sinonimi : "";
  $("#art-attivo").checked = !r || !!r.attivo;
  $("#articolo-errore").textContent = "";
  $("#articolo-elimina").classList.toggle("nascosto", !r);
  $("#unita-note").innerHTML = ["Pz", "Ml", "Mq", "Mc", "KG", "Ton"].map(u => `<option value="${u}">`).join("");
  $("#dialogo-articolo").showModal();
}
$("#articolo-chiudi").addEventListener("click", () => $("#dialogo-articolo").close());
$("#articolo-elimina").addEventListener("click", async () => {
  const r = a.articoloAperto;
  if (!confirm(`Eliminare l'articolo ${r.codice}? Non si può annullare.`)) return;
  try {
    await api(`/api/admin/articoli/${r.id}`, { method: "DELETE" });
    $("#dialogo-articolo").close(); caricaArticoli();
  } catch (e) { $("#articolo-errore").textContent = e.message; }
});
$("#articolo-salva").addEventListener("click", async () => {
  const dati = { codice: $("#art-codice").value, unita: $("#art-unita").value, descrizione: $("#art-descrizione").value,
                 sinonimi: $("#art-sinonimi").value, attivo: $("#art-attivo").checked, misure_auto: !$("#art-verificate").checked };
  for (const c of ["spessore", "larghezza", "lunghezza", "trasversali"]) {
    const n = leggiNumero($(`#art-${c}`).value);
    if (Number.isNaN(n)) { $("#articolo-errore").textContent = `${c}: numero non valido`; return; }
    dati[c] = n;
  }
  try {
    const r = a.articoloAperto;
    await api(r ? `/api/admin/articoli/${r.id}` : "/api/admin/articoli", { method: r ? "PUT" : "POST", json: dati });
    $("#dialogo-articolo").close(); caricaArticoli();
  } catch (e) { $("#articolo-errore").textContent = e.message; }
});

// --- Utenti --------------------------------------------------------------------------
async function caricaUtenti() {
  a.utenti = await api("/api/admin/utenti");
  $("#utenti").innerHTML = a.utenti.map(u => `<div class="riga-elenco">
      <div class="testo"><b>${esc(u.nome)}</b> <span class="tenue">· ${u.ruolo}${u.attivo ? "" : " · disattivato"}</span></div>
      <button class="btn piccolo" data-pin="${u.id}">Nuovo ${u.ruolo === "admin" ? "password" : "PIN"}</button>
      <button class="btn piccolo ${u.attivo ? "pericolo" : ""}" data-attiva="${u.id}">${u.attivo ? "Disattiva" : "Riattiva"}</button>
    </div>`).join("");
}
$("#form-utente").addEventListener("submit", async e => {
  e.preventDefault();
  $("#errore-utenti").textContent = "";
  try {
    await api("/api/admin/utenti", { json: { nome: $("#nuovo-nome").value, ruolo: $("#nuovo-ruolo").value, pin: $("#nuovo-pin").value } });
    $("#form-utente").reset(); caricaUtenti();
  } catch (err) { $("#errore-utenti").textContent = err.message; }
});
$("#utenti").addEventListener("click", async e => {
  const b = e.target.closest("button");
  if (!b) return;
  const u = a.utenti.find(x => x.id === Number(b.dataset.pin || b.dataset.attiva));
  $("#errore-utenti").textContent = "";
  try {
    if (b.dataset.pin) {
      const pin = prompt(u.ruolo === "admin" ? `Nuova password per ${u.nome} (almeno 8 caratteri)` : `Nuovo PIN di 4 cifre per ${u.nome}`);
      if (!pin) return;
      await api(`/api/admin/utenti/${u.id}`, { method: "PUT", json: { ruolo: u.ruolo, attivo: !!u.attivo, pin } });
      alert("Fatto.");
    } else {
      await api(`/api/admin/utenti/${u.id}`, { method: "PUT", json: { ruolo: u.ruolo, attivo: !u.attivo } });
    }
    caricaUtenti();
  } catch (err) { $("#errore-utenti").textContent = err.message; }
});

// --- Zone ----------------------------------------------------------------------------
async function caricaZone() {
  a.zone = await api("/api/admin/zone");
  $("#zone").innerHTML = a.zone.map(z => `<div class="riga-elenco">
      <div class="testo">${esc(z.nome)}${z.attiva ? "" : ' <span class="tenue">· disattivata</span>'}</div>
      <button class="btn piccolo" data-zona="${z.id}" data-attiva="${z.attiva ? 0 : 1}">${z.attiva ? "Disattiva" : "Riattiva"}</button>
    </div>`).join("");
}
$("#form-zona").addEventListener("submit", async e => {
  e.preventDefault();
  await api("/api/admin/zone", { json: { nome: $("#nuova-zona").value } });
  $("#form-zona").reset(); caricaZone();
});
$("#zone").addEventListener("click", async e => {
  const b = e.target.closest("button[data-zona]");
  if (!b) return;
  await api(`/api/admin/zone/${b.dataset.zona}`, { method: "PUT", json: { attiva: b.dataset.attiva === "1" } });
  caricaZone();
});

// --- Chiusura dell'inventario ------------------------------------------------------------
$("#archivia").addEventListener("click", async () => {
  if (!confirm("Archiviare l'inventario con la data di oggi? L'elenco verrà svuotato (le righe restano nell'archivio).")) return;
  await api("/api/admin/chiudi", { json: { modo: "archivia" } });
  alert("Inventario archiviato."); aggiornaStato();
});
$("#cancella").addEventListener("click", async () => {
  const conferma = prompt('Le righe dell\'inventario in corso verranno ELIMINATE definitivamente. Scrivi CANCELLA per confermare.');
  if (conferma !== "CANCELLA") return;
  await api("/api/admin/chiudi", { json: { modo: "cancella" } });
  alert("Inventario cancellato."); aggiornaStato();
});

$("#esci").addEventListener("click", async () => {
  try { await api("/api/uscita", { method: "POST" }); } catch { /* pazienza */ }
  location.href = "/login";
});

(async () => {
  await caricaFiltri();
  caricaRighe();
  aggiornaStato();
})();
