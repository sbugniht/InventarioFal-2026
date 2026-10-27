// Mappa satellitare dell'azienda: aree (i terreni) e zone dentro le aree.
// Vista d'insieme con le aree; toccando un'area si ingrandisce e mostra le sue zone colorate.
// La usano l'operatore (scegliere la zona) e l'admin (disegnare i contorni, vedi disegnaContorno).
// I contorni sono [[x, y], ...] da 0 a 1 rispetto all'immagine (come in api.py).

const SVG_NS = "http://www.w3.org/2000/svg";
const COLORI_ZONE = ["#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6",
                     "#bfef45", "#fabed4", "#469990", "#dcbeff", "#9a6324", "#800000", "#aaffc3", "#000075"];

function elementoSvg(nome, attributi = {}) {
  const e = document.createElementNS(SVG_NS, nome);
  for (const [k, v] of Object.entries(attributi)) e.setAttribute(k, v);
  return e;
}

// Colore scelto dall'admin, altrimenti uno fisso per zona (uguale su tutti i dispositivi)
function coloreZona(z) {
  return z.colore || COLORI_ZONE[z.id % COLORI_ZONE.length];
}

class Mappa {
  // info: {larghezza, altezza, crediti}; scegliZona(id): chiamata quando si tocca una zona sulla mappa
  constructor(contenitore, { info, aree = [], zone = [], scegliZona = null }) {
    this.W = info.larghezza; this.H = info.altezza;
    this.scegliZona = scegliZona;
    this.areaAperta = null; this.zonaScelta = null; this.zonaAccesa = null;
    this.vista = [0, 0, this.W, this.H];
    contenitore.innerHTML = "";
    contenitore.classList.add("mappa");
    this.svg = elementoSvg("svg", { viewBox: this.vista.join(" "), preserveAspectRatio: "xMidYMid meet" });
    this.svg.append(elementoSvg("image", { href: "/mappa/immagine", x: 0, y: 0, width: this.W, height: this.H }));
    this.gAree = elementoSvg("g"); this.gZone = elementoSvg("g");
    this.gScritte = elementoSvg("g", { "pointer-events": "none" }); this.gDisegno = elementoSvg("g");
    this.svg.append(this.gAree, this.gZone, this.gScritte, this.gDisegno);
    this.indietro = document.createElement("button");
    this.indietro.className = "btn piccolo mappa-indietro nascosto";
    this.indietro.textContent = "← Tutte le aree";
    this.indietro.addEventListener("click", () => this.mostraTutto());
    const crediti = document.createElement("div");
    crediti.className = "mappa-crediti";
    crediti.textContent = info.crediti || "";
    contenitore.append(this.svg, this.indietro, crediti);
    this.aggiorna(aree, zone);
    this.mostraTutto();
  }

  // Nuovi dati (dopo una modifica dell'admin o un catalogo scaricato)
  aggiorna(aree, zone) {
    this.aree = aree; this.zone = zone;
    this.colori = new Map(zone.map(z => [z.id, coloreZona(z)]));
    this.gAree.innerHTML = ""; this.gZone.innerHTML = "";
    for (const a of aree.filter(a => a.forma)) {
      const p = elementoSvg("polygon", { points: this._punti(a.forma), class: "mappa-area", "data-area": a.id });
      p.style.setProperty("--colore", a.colore);
      p.addEventListener("click", () => this._toccaArea(a.id));
      this.gAree.append(p);
    }
    for (const z of zone.filter(z => z.forma)) {
      const p = elementoSvg("polygon", { points: this._punti(z.forma), class: "mappa-zona", "data-zona": z.id });
      p.style.setProperty("--colore", this.colori.get(z.id));
      p.addEventListener("click", e => {
        // Nella vista d'insieme si tocca l'area (si ingrandisce); dentro l'area si sceglie la zona
        if (this._disegno || (z.area_id && this.areaAperta !== z.area_id)) return;
        e.stopPropagation();
        if (this.scegliZona) this.scegliZona(z.id);
      });
      this.gZone.append(p);
    }
    this._stato();
  }

  // Vista d'insieme: tutte le aree disegnate (o l'immagine intera se non ce ne sono)
  mostraTutto() {
    this.areaAperta = null;
    const forme = [...this.aree, ...this.zone].map(x => x.forma).filter(Boolean);
    this._vai(forme.length ? this._riquadro(forme) : [0, 0, this.W, this.H]);
    this._stato();
  }

  apriArea(id) {
    const area = this.aree.find(a => a.id === id);
    const forme = [area?.forma, ...this.zone.filter(z => z.area_id === id).map(z => z.forma)].filter(Boolean);
    if (!forme.length) return;
    this.areaAperta = id;
    this._vai(this._riquadro(forme));
    this._stato();
  }

  // Zona scelta (resta accesa); null = nessuna
  scegli(id) {
    this.zonaScelta = id;
    const z = this.zone.find(z => z.id === id);
    if (z?.area_id && z.area_id !== this.areaAperta) this.apriArea(z.area_id);
    this._stato();
  }

  // Zona accesa di passaggio (mouse sopra una voce dell'elenco); null = torna alla scelta
  accendi(id) {
    this.zonaAccesa = id;
    // Finito il passaggio si torna all'area della zona scelta
    const z = this.zone.find(z => z.id === (id ?? this.zonaScelta));
    if (z?.area_id && z.area_id !== this.areaAperta) this.apriArea(z.area_id);
    this._stato();
  }

  // Disegno (admin): si tocca per aggiungere punti, si trascinano i punti per spostarli.
  // Torna un oggetto con punti(), togliUltimo(), chiudi(); onCambio(punti) a ogni modifica.
  disegnaContorno({ iniziale = null, colore = "#ffeb3b", onCambio = () => {} } = {}) {
    this.chiudiDisegno();
    let punti = (iniziale || []).map(p => [...p]);
    const poligono = elementoSvg("polygon", { class: "mappa-disegno" });
    poligono.style.setProperty("--colore", colore);
    const maniglie = elementoSvg("g");
    let trascinato = false;  // finito un trascinamento il browser manda anche un clic: non è un punto nuovo
    this.gDisegno.append(poligono, maniglie);
    this.svg.classList.add("disegno");
    const ridisegna = () => {
      poligono.setAttribute("points", this._punti(punti));
      maniglie.innerHTML = "";
      const raggio = 7 * this._perPixel();  // maniglie di circa 14 px, comode anche col dito
      punti.forEach((p, i) => {
        const c = elementoSvg("circle", { cx: p[0] * this.W, cy: p[1] * this.H, r: raggio, class: "mappa-maniglia" });
        c.addEventListener("pointerdown", e => {
          e.stopPropagation(); e.preventDefault();
          const muovi = ev => { punti[i] = this._coordinate(ev); trascinato = true; ridisegna(); };
          const fine = () => {
            window.removeEventListener("pointermove", muovi); window.removeEventListener("pointerup", fine);
            setTimeout(() => { trascinato = false; });  // dopo il clic che segue il rilascio
            onCambio(punti);
          };
          window.addEventListener("pointermove", muovi); window.addEventListener("pointerup", fine);
        });
        maniglie.append(c);
      });
    };
    const aggiungi = e => {
      if (trascinato || e.target.classList?.contains("mappa-maniglia")) return;
      punti.push(this._coordinate(e)); ridisegna(); onCambio(punti);
    };
    this.svg.addEventListener("click", aggiungi, true);
    ridisegna();
    this._disegno = {
      punti: () => punti.map(p => [...p]),
      togliUltimo: () => { punti.pop(); ridisegna(); onCambio(punti); },
      chiudi: () => {
        this.svg.removeEventListener("click", aggiungi, true);
        this.svg.classList.remove("disegno");
        this.gDisegno.innerHTML = "";
        this._disegno = null;
      },
    };
    return this._disegno;
  }

  chiudiDisegno() { if (this._disegno) this._disegno.chiudi(); }

  // --- interni ---------------------------------------------------------------------
  _toccaArea(id) {
    if (this._disegno || this.areaAperta === id) return;
    this.apriArea(id);
    // Area con una sola zona (es. Uffici): toccarla basta per sceglierla
    const sue = this.zone.filter(z => z.area_id === id);
    if (sue.length === 1 && this.scegliZona) this.scegliZona(sue[0].id);
  }

  _punti(forma) { return forma.map(([x, y]) => `${x * this.W},${y * this.H}`).join(" "); }

  // Rettangolo (viewBox) che contiene i contorni, con un po' di margine
  _riquadro(forme) {
    const xs = forme.flat().map(p => p[0] * this.W), ys = forme.flat().map(p => p[1] * this.H);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const margine = Math.max(x1 - x0, y1 - y0) * 0.08;
    return [x0 - margine, y0 - margine, x1 - x0 + 2 * margine, y1 - y0 + 2 * margine];
  }

  // Unità della mappa per pixel dello schermo, con la vista attuale
  _perPixel() {
    const r = this.svg.getBoundingClientRect();
    if (!r.width || !r.height) return this.vista[2] / 600;
    return Math.max(this.vista[2] / r.width, this.vista[3] / r.height);
  }

  _coordinate(evento) {
    const p = this.svg.createSVGPoint();
    p.x = evento.clientX; p.y = evento.clientY;
    const q = p.matrixTransform(this.svg.getScreenCTM().inverse());
    const limita = v => Math.round(Math.min(1, Math.max(0, v)) * 100000) / 100000;
    return [limita(q.x / this.W), limita(q.y / this.H)];
  }

  // Ingrandimento animato (viewBox)
  _vai(arrivo) {
    const partenza = [...this.vista], inizio = performance.now(), durata = 350;
    cancelAnimationFrame(this._animazione);
    const passo = adesso => {
      const t = Math.min(1, (adesso - inizio) / durata), k = 1 - Math.pow(1 - t, 3);
      this.vista = partenza.map((v, i) => v + (arrivo[i] - v) * k);
      this.svg.setAttribute("viewBox", this.vista.join(" "));
      if (t < 1) this._animazione = requestAnimationFrame(passo);
      else this._scritte();
    };
    this._animazione = requestAnimationFrame(passo);
  }

  // Classi (accesa, scelta, dentro l'area aperta) e scritte
  _stato() {
    const aperta = this.areaAperta;
    this.indietro.classList.toggle("nascosto", aperta === null);
    for (const p of this.gAree.children) {
      p.classList.toggle("aperta", Number(p.dataset.area) === aperta);
      p.classList.toggle("chiusa", aperta !== null && Number(p.dataset.area) !== aperta);
    }
    for (const p of this.gZone.children) {
      const id = Number(p.dataset.zona), z = this.zone.find(z => z.id === id);
      p.classList.toggle("visibile", aperta === null ? !z.area_id : z.area_id === aperta);
      p.classList.toggle("scelta", id === this.zonaScelta);
      p.classList.toggle("accesa", id === this.zonaAccesa);
    }
    this._scritte();
  }

  _scritte() {
    this.gScritte.innerHTML = "";
    const dimensione = 15 * this._perPixel();  // circa 15 px sullo schermo, a qualunque ingrandimento
    const scrivi = (testo, forma) => {
      const cx = forma.reduce((s, p) => s + p[0], 0) / forma.length * this.W;
      const cy = forma.reduce((s, p) => s + p[1], 0) / forma.length * this.H;
      const t = elementoSvg("text", { x: cx, y: cy, class: "mappa-scritta", "font-size": dimensione,
                                      "stroke-width": dimensione / 6 });
      t.textContent = testo;
      this.gScritte.append(t);
    };
    if (this.areaAperta === null) {
      for (const a of this.aree.filter(a => a.forma)) scrivi(a.nome, a.forma);
      for (const z of this.zone.filter(z => z.forma && !z.area_id)) scrivi(z.nome, z.forma);
    } else {
      for (const z of this.zone.filter(z => z.forma && z.area_id === this.areaAperta)) scrivi(z.nome, z.forma);
    }
  }
}
