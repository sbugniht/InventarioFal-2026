// Funzioni comuni a tutte le pagine.

class ErroreApi extends Error {
  constructor(messaggio, stato) { super(messaggio); this.stato = stato; }
}

// Chiamata alle API. Senza rete lancia ErroreApi con stato 0.
async function api(url, opzioni = {}) {
  const init = { credentials: "same-origin", ...opzioni };
  if (opzioni.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opzioni.json);
    delete init.json;
  }
  let risposta;
  try {
    risposta = await fetch(url, init);
  } catch (e) {
    throw new ErroreApi("Nessuna connessione con il server", 0);
  }
  if (risposta.status === 401 && !location.pathname.startsWith("/login")) {
    location.href = "/login";
    throw new ErroreApi("Accesso richiesto", 401);
  }
  const dati = await risposta.json().catch(() => ({}));
  if (!risposta.ok) throw new ErroreApi(dati.errore || `Errore ${risposta.status}`, risposta.status);
  return dati;
}

// localStorage può non essere disponibile (navigazione privata): mai bloccare la pagina per questo
const memoria = {
  leggi(chiave, predefinito = null) {
    try { const v = localStorage.getItem(chiave); return v === null ? predefinito : JSON.parse(v); }
    catch { return predefinito; }
  },
  scrivi(chiave, valore) {
    try { localStorage.setItem(chiave, JSON.stringify(valore)); return true; } catch { return false; }
  },
};

function esc(testo) {
  return String(testo ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function $(selettore, radice = document) { return radice.querySelector(selettore); }

// Numeri all'italiana: 2,5 -> "2,5"; null -> ""
function formatoNumero(n) {
  if (n === null || n === undefined || n === "") return "";
  return Number(n).toLocaleString("it-IT", { maximumFractionDigits: 3 });
}
function leggiNumero(testo) {
  const t = String(testo ?? "").trim().replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

// Suoni: "ok" al salvataggio, "errore" per campi mancanti o errori
let contestoAudio = null;
function beep(tipo = "ok") {
  try {
    contestoAudio = contestoAudio || new (window.AudioContext || window.webkitAudioContext)();
    const note = tipo === "ok" ? [[880, 0], [1320, 0.12]] : [[220, 0], [180, 0.18]];
    for (const [frequenza, ritardo] of note) {
      const osc = contestoAudio.createOscillator();
      const gain = contestoAudio.createGain();
      osc.type = tipo === "ok" ? "sine" : "square";
      osc.frequency.value = frequenza;
      const inizio = contestoAudio.currentTime + ritardo;
      gain.gain.setValueAtTime(0.25, inizio);
      gain.gain.exponentialRampToValueAtTime(0.001, inizio + 0.16);
      osc.connect(gain).connect(contestoAudio.destination);
      osc.start(inizio);
      osc.stop(inizio + 0.17);
    }
  } catch { /* audio non disponibile: pazienza */ }
}

// Messaggio a tutto schermo che scompare da solo (anche se il testo è uguale al precedente)
function lampo(testo, sbagliato = false) {
  const div = document.createElement("div");
  div.className = "lampo" + (sbagliato ? " sbagliato" : "");
  div.textContent = testo;
  document.body.appendChild(div);
  setTimeout(() => div.remove(), 1500);
}

function idUnivoco() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

// Data e ora locali, senza fuso: "2026-10-25T14:03:12"
function adessoLocale() {
  const d = new Date();
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// Pagina disponibile anche senza rete (service worker)
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
