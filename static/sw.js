// Service worker: tiene una copia delle pagine per aprirle anche senza rete.
// Prima prova la rete (così gli aggiornamenti arrivano subito), se manca usa la copia.
const CACHE = "inventario-v2";
const PAGINE = ["/login", "/operatore", "/static/stile.css", "/static/comune.js", "/static/operatore.js",
                "/static/mappa.js"];
// La mappa può mancare (dati/mappa non configurata): si tiene in copia quando c'è, ma non all'installazione
const FACOLTATIVE = ["/mappa/immagine"];

self.addEventListener("install", evento => {
  evento.waitUntil(caches.open(CACHE).then(c => c.addAll(PAGINE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", evento => {
  evento.waitUntil(
    caches.keys()
      .then(chiavi => Promise.all(chiavi.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", evento => {
  const url = new URL(evento.request.url);
  // Le API non si mettono in cache: i dati arrivano sempre dal server (o dalla coda del tablet)
  if (evento.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  if (!PAGINE.includes(url.pathname) && !FACOLTATIVE.includes(url.pathname)) return;
  evento.respondWith(
    fetch(evento.request)
      .then(risposta => {
        if (risposta.ok && !risposta.redirected) {
          const copia = risposta.clone();
          caches.open(CACHE).then(c => c.put(evento.request, copia));
        }
        return risposta;
      })
      .catch(() => caches.match(evento.request))
  );
});
