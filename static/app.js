/* SusMob SPA – Kacheln, Chat (SSE), Standardwerte, Admin-Prompts */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = $("#view");

const state = {
  tiles: [],
  tile: null,
  convs: [],
  conv: null,
  std: [],
  busy: false,
  admin: { token: localStorage.getItem("susmob_admin") || "", tab: "kacheln" },
  adminTiles: [],
  adminTile: null,
  testCases: [],
};

let toastTimer = null;
function toast(msg) {
  let t = $(".toast");
  if (t) t.remove();
  t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 3200);
}

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (state.admin.token && path.startsWith("/api/admin")) headers["X-Admin-Token"] = state.admin.token;
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) {
    let m = r.statusText;
    try { m = (await r.json()).detail || m; } catch { /* ignore */ }
    throw new Error(m);
  }
  return r.json();
}

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function fmtBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " kB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

/* ---------- Mini-Markdown (reicht für Bot-Antworten) ---------- */
function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function md(src) {
  if (!src) return "";
  const blocks = [];
  src = src.replace(/```([\w-]*)\n?([\s\S]*?)```/g, (m, _lang, code) => {
    blocks.push(`<pre class="code"><code>${esc(code.replace(/\n$/, ""))}</code></pre>`);
    return `\u0000B${blocks.length - 1}\u0000`;
  });
  const lines = src.split("\n");
  let html = "", inUl = false, inOl = false, table = null;
  const closeLists = () => { if (inUl) { html += "</ul>"; inUl = false; } if (inOl) { html += "</ol>"; inOl = false; } };
  const closeTable = () => {
    if (table) {
      let h = "<table><tbody>";
      if (table.head.length) h += "<tr>" + table.head.map(c => `<th>${c}</th>`).join("") + "</tr>";
      h += table.rows.map(r => "<tr>" + r.map(c => `<td>${c}</td>`).join("") + "</tr>").join("");
      html += h + "</tbody></table>";
      table = null;
    }
  };
  for (const raw of lines) {
    const t = raw.trim().replace(/\u0000B(\d+)\u0000/g, (m, i) => blocks[+i]);
    if (/^\|.*\|$/.test(t)) {
      const cells = t.split("|").slice(1, -1).map(c => inline(c.trim()));
      if (!table) table = { head: [], rows: [] };
      if (cells.every(c => /^:?-{2,}:?$/.test(c))) continue;
      if (!table.head.length) { table.head = cells; continue; }
      table.rows.push(cells);
      continue;
    }
    closeTable();
    if (!t) { closeLists(); continue; }
    let m;
    if ((m = t.match(/^(#{1,4})\s+(.*)/))) { closeLists(); html += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; continue; }
    if (/^(-{3,}|\*{3,})$/.test(t)) { closeLists(); html += "<hr>"; continue; }
    if ((m = t.match(/^[-*]\s+(.*)/))) {
      if (inOl) { html += "</ol>"; inOl = false; }
      if (!inUl) { html += "<ul>"; inUl = true; }
      html += `<li>${inline(m[1])}</li>`; continue;
    }
    if ((m = t.match(/^\d+[.)]\s+(.*)/))) {
      if (inUl) { html += "</ul>"; inUl = false; }
      if (!inOl) { html += "<ol>"; inOl = true; }
      html += `<li>${inline(m[1])}</li>`; continue;
    }
    closeLists();
    html += `<p>${inline(t)}</p>`;
  }
  closeLists(); closeTable();
  return html;
}

/* ---------- Router ---------- */
window.addEventListener("hashchange", route);
function navActive(id) {
  $$(".topbar nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === id));
}
function route() {
  const h = location.hash || "#/";
  let m;
  if (h === "#/" || h === "#") return viewHome();
  if ((m = h.match(/^#\/tile\/([\w-]+)(?:\/([\w-]+))?/))) return viewTile(m[1], m[2]);
  if (h === "#/admin") return viewAdmin();
  viewHome();
}

/* ---------- Home ---------- */
async function viewHome() {
  navActive("home");
  view.innerHTML = `<div class="homehead"><h1>Mobilität für deine Kommune</h1>
    <p>Kachel wählen · Daten hochladen · mit dem Fach-Bot chatten · Ergebnis erhalten.</p></div>
    <div class="tiles" id="tiles">Lädt …</div>`;
  try {
    state.tiles = await api("/api/tiles");
  } catch (e) {
    $("#tiles").innerHTML = `<p class="errbox">API nicht erreichbar: ${esc(e.message)}</p>`;
    return;
  }
  $("#tiles").innerHTML = state.tiles.map(t => `
    <div class="tile">
      <a class="tilemain" href="#/tile/${t.id}">
        <div class="emoji">${t.emoji}</div>
        <h3>${esc(t.name)}</h3>
        <p>${esc(t.short)}</p>
        <span class="go">Starten →</span>
      </a>
      <a class="tileexample" href="#/tile/${t.id}/beispiel" title="Gespeicherten Beispiellauf dieser Kachel ansehen">📘 Beispiel ansehen</a>
    </div>`).join("");
}

/* ---------- Tile-Ansicht ---------- */
async function viewTile(tid, sub) {
  navActive("home");
  state.tile = null; state.conv = null;
  state.wantExample = sub === "beispiel";
  view.innerHTML = `<div class="tilehead"><span style="color:var(--muted)">Lädt …</span></div>`;
  let tile;
  try { tile = (await api("/api/tiles")).find(t => t.id === tid); } catch (e) { return errView(e); }
  if (!tile) return errView(new Error("Kachel nicht gefunden"));
  state.tile = tile;
  view.innerHTML = `
    <div class="tilehead">
      <a class="back" href="#/">← Kacheln</a>
      <div class="tiletitle">
        <span class="emoji">${tile.emoji}</span>
        <div><h2>${esc(tile.name)}</h2><div class="sub">${esc(tile.short)}</div></div>
      </div>
      <div class="actions">
        <button class="btn ghost" id="stdToggle">⚙️ Standardwerte</button>
        <button class="btn primary" id="newConv">+ Neue Unterhaltung</button>
      </div>
    </div>
    <div id="stdPanel" class="stdpanel hidden"></div>
    <div class="tilebody">
      <aside class="convs">
        <div class="convs-head">Unterhaltungen</div>
        <div id="convList"></div>
      </aside>
      <section class="chat">
        <div class="examplebar hidden" id="exampleBar"></div>
        <div class="chatbar">
          <span class="label">Ergebnis:</span>
          <button class="btn tiny" id="btnAuswertung" title="Modell extrahiert Daten → SusMob rechnet nach (Phase 1/2)">📊 Auswerten &amp; rechnen</button>
          <button class="btn tiny" id="btnXlsx" title="Excel mit Formeln und Annahmen-Blatt">⬇️ .xlsx</button>
          <button class="btn tiny" id="btnJson" title="Maschinenlesbare Auswertung">🧾 .json</button>
          <button class="btn tiny" id="btnPrint" title="Druckansicht für PDF (Amtslook, Briefkopf-Platzhalter)">🖨️ Druckansicht (PDF)</button>
          <span class="grow"></span>
          <span class="chatmeta" id="chatMeta"></span>
        </div>
        <div id="auswertungBox" class="auswertung hidden"></div>
        <div id="artifactBox" class="artifactbox hidden"></div>
        <div id="msgArea"></div>
        <div class="filechips" id="fileChips"></div>
        <div class="composer" id="composerBox">
          <label class="attach" title="Datei anhängen (txt, csv, xlsx, docx, pdf …)">📎
            <input type="file" id="fileInput" multiple>
          </label>
          <textarea id="msgInput" rows="2" placeholder="Frage stellen, Daten beschreiben oder Datei anhängen …"></textarea>
          <button class="btn primary" id="sendBtn">Senden</button>
        </div>
      </section>
    </div>`;

  await loadConvs(tid);
  renderBetriebsHinweis();
  if ($("#btnAuswertung")) $("#btnAuswertung").onclick = auswerten;
  if ($("#btnXlsx")) $("#btnXlsx").onclick = () => exportieren("xlsx");
  if ($("#btnJson")) $("#btnJson").onclick = () => exportieren("json");
  if ($("#btnPrint")) $("#btnPrint").onclick = druckAnsicht;
  if ($("#stdToggle")) $("#stdToggle").onclick = () => toggleStd();
  $("#newConv").onclick = async () => {
    const r = await api("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tile_id: tid }) });
    await loadConvs(tid);
    openConv(r.id);
  };
  $("#sendBtn").onclick = sendMsg;
  $("#msgInput").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); }
  });
  $("#fileInput").addEventListener("change", onFiles);

  const example = state.convs.find(c => c.is_example);
  if (state.wantExample && example) openConv(example.id);
  else if (state.convs.length) openConv(state.convs[0].id);
  else renderEmptyChat();
}

/* Betriebs-/Datenschutzhinweis: Demo-Betrieb und Gratis-Kontingent transparent machen */
async function renderBetriebsHinweis() {
  const box = $("#chatBar");
  let st = null;
  try { st = await api("/api/status"); } catch { /* offline egal */ }
  if (!st) return;
  const teile = [];
  if (st.demo_only) {
    teile.push("⚠️ **Demo-Betrieb mit Gratis-Modellen** – Anbieter dürfen Prompts zum Training nutzen. " +
      "Keine echten Personen- oder Kommunaldaten hochladen.");
  }
  const l = st.limits || {};
  if (l.tagesbudget) {
    teile.push(`🔋 Test-Kontingent: **${st.rest_heute}** von ${l.tagesbudget} Modell-Aufrufen heute frei`
      + (l.pro_stunde ? ` · max. ${l.pro_stunde}/Stunde` : ""));
  }
  if (!st.api_key) teile.push("🔌 Kein API-Key gesetzt – Chat läuft im Demo-Modus (Beispiele & Export funktionieren).");
  if (!st.live_liste && st.api_key) teile.push("🌐 OpenRouter ist von diesem Server aus nicht erreichbar – " +
    "Beispiele, Auswertung aus dem Antworttext und Excel-Export funktionieren trotzdem.");
  if (!teile.length) return;
  const el = document.createElement("div");
  el.className = "betriebshinweis";
  el.innerHTML = teile.join("<br>");
  box.insertAdjacentElement("afterend", el);
}

function errView(e) {
  view.innerHTML = `<div class="empty"><div class="big">😕</div><p>${esc(e.message)}</p></div>`;
}

async function loadConvs(tid) {
  state.convs = await api("/api/conversations?tile_id=" + encodeURIComponent(tid));
  const list = $("#convList");
  if (!list) return;
  const mine = state.convs.filter(c => !c.is_example);
  const examples = state.convs.filter(c => c.is_example);
  const cls = c => `convitem ${c.is_example ? "example" : ""} ${state.conv && state.conv.id === c.id ? "active" : ""}`;
  const label = c => esc(String(c.title).replace(/^📘\s*/, ""));
  let html = "";
  if (examples.length) {
    html += `<div class="convs-sub">📘 Beispiele (schreibgeschützt)</div>`;
    html += examples.map(c => `
      <div class="${cls(c)}" data-cid="${c.id}" title="Beispiellauf ansehen">
        <span class="t">${label(c)}</span>
      </div>`).join("");
  }
  html += `<div class="convs-sub">Eigene Unterhaltungen</div>`;
  html += mine.length
    ? mine.map(c => `
      <div class="${cls(c)}" data-cid="${c.id}">
        <span class="t" title="${esc(c.title)}">${label(c)}</span>
        <span class="del" title="Löschen" data-del="${c.id}">✕</span>
      </div>`).join("")
    : `<div class="convs-empty">Noch keine eigene Unterhaltung – „+ Neue Unterhaltung“ oder ein Beispiel übernehmen.</div>`;
  list.innerHTML = html;
  $$(".convitem", list).forEach(el => {
    el.onclick = () => openConv(el.dataset.cid);
  });
  $$(".convitem .del", list).forEach(el => {
    el.onclick = async ev => {
      ev.stopPropagation();
      if (!confirm("Unterhaltung wirklich löschen?")) return;
      await api("/api/conversations/" + el.dataset.del, { method: "DELETE" });
      state.conv = null;
      await loadConvs(state.tile.id);
      renderEmptyChat();
    };
  });
}

function renderEmptyChat() {
  const area = $("#msgArea");
  const s = state.tile.suggestions || [];
  const ex = (state.convs || []).find(c => c.is_example);
  area.innerHTML = `<div class="empty">
    <div class="big">${state.tile.emoji}</div>
    <p><strong>${esc(state.tile.name)}</strong> – Daten hochladen (📎) oder direkt loslegen.</p>
    ${ex ? `<p class="hint">Noch unsicher? <a href="#/tile/${state.tile.id}/beispiel">📘 Beispiel dieser Kachel ansehen</a></p>` : ""}
    ${s.length ? `<div class="sugg">${s.map(x => `<button data-sugg="${esc(x)}">${esc(x.slice(0, 64))}${x.length > 64 ? "…" : ""}</button>`).join("")}</div>` : ""}
  </div>`;
  $$("#msgArea .sugg button").forEach(b => {
    b.onclick = () => { $("#msgInput").value = b.dataset.sugg; $("#msgInput").focus(); };
  });
}

async function openConv(cid) {
  const vorher = state.conv?.id;
  try { state.conv = await api("/api/conversations/" + cid); }
  catch (e) { return toast("Fehler: " + e.message); }
  if (vorher !== cid) state.auswertung = null;
  $$("#convList .convitem").forEach(el => el.classList.toggle("active", el.dataset.cid === cid));
  renderMessages();
  renderFiles();
  renderExampleBar();
  renderArtifacts();
  renderConversationMeta();
}

/* Konversations-Summe: Tokens & Kosten (Phase 0 – gemessen, nicht geschätzt) */
function renderConversationMeta() {
  const el = $("#chatMeta");
  if (!el) return;
  const k = state.conv?.kosten || {};
  if (!k.calls) { el.textContent = ""; return; }
  const usd = Number(k.kosten_usd || 0);
  el.innerHTML = `Σ ${k.calls} Calls · ${Number(k.tokens || 0).toLocaleString("de-DE")} Tokens · ` +
    `${usd < 0.01 ? usd.toFixed(5) : usd.toFixed(3)} $` +
    (Number(k.geschaetzt) ? ` <span title="Teilweise geschätzt (keine usage im Response)">≈</span>` : "");
}

/* ---------- Auswertung, Export, Druck (Phase 1) ---------- */
function chartDonut(items, size = 180) {
  const data = items.filter(i => Number(i.wert) > 0);
  const total = data.reduce((s, i) => s + Number(i.wert), 0);
  if (!total) return "";
  const farben = ["#38bdf8", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#22d3ee", "#f472b6"];
  let angle = -Math.PI / 2, paths = "";
  const cx = size / 2, cy = size / 2, r = size / 2 - 4, ri = r * 0.58;
  data.forEach((d, i) => {
    const frac = Number(d.wert) / total;
    const a2 = angle + frac * Math.PI * 2;
    const large = frac > 0.5 ? 1 : 0;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
    const x3 = cx + ri * Math.cos(a2), y3 = cy + ri * Math.sin(a2);
    const x4 = cx + ri * Math.cos(angle), y4 = cy + ri * Math.sin(angle);
    paths += `<path d="M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)} ` +
      `L${x3.toFixed(1)},${y3.toFixed(1)} A${ri},${ri} 0 ${large} 0 ${x4.toFixed(1)},${y4.toFixed(1)} Z" ` +
      `fill="${farben[i % farben.length]}" opacity="0.9"><title>${esc(d.label)}: ${d.wert}</title></path>`;
    angle = a2;
  });
  const legende = data.map((d, i) => `<li><span class="dot" style="background:${farben[i % farben.length]}"></span>` +
    `${esc(d.label)} <b>${esc(String(d.wert))}</b> <span class="muted">(${(Number(d.wert) / total * 100).toFixed(1)} %)</span></li>`).join("");
  return `<div class="chartbox"><svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">${paths}` +
    `<circle cx="${cx}" cy="${cy}" r="${ri - 2}" fill="rgba(0,0,0,0)"/></svg><ul class="legend">${legende}</ul></div>`;
}

function chartBars(items, { max = null, einheit = "" } = {}) {
  const data = items.filter(i => i.wert !== null && i.wert !== undefined);
  if (!data.length) return "";
  const grenze = max || Math.max(...data.map(d => Number(d.wert)), 1);
  return `<div class="bars">${data.map(d => {
    const pct = Math.max(2, Math.min(100, Number(d.wert) / grenze * 100));
    return `<div class="barrow"><span class="bl">${esc(d.label)}</span>
      <span class="btrack"><span class="bfill" style="width:${pct.toFixed(1)}%"></span></span>
      <span class="bv">${esc(String(d.wert))}${einheit}</span></div>`;
  }).join("")}</div>`;
}

function auswertungHTML(a) {
  const calc = a.berechnet || {};
  const strukturiert = a.strukturiert || {};
  let charts = "";
  if (calc.typ === "co2_bilanz" && (calc.gruppen || []).length) {
    const daten = calc.gruppen.map(g => ({ label: g.bezeichnung, wert: g.t_co2 }));
    charts += `<div class="charttitle">Emissionsanteile (berechnet)</div>${chartDonut(daten)}` +
      chartBars(daten.map(d => ({ label: d.label, wert: d.wert })), { einheit: " t CO₂/a" });
  }
  if (calc.typ === "massnahmen_priorisierung" && (calc.massnahmen || []).length) {
    charts += `<div class="charttitle">Priorisierung (Nutzwertanalyse)</div>` +
      chartBars(calc.massnahmen.map(m => ({ label: `${m.rang}. ${m.name}`, wert: m.score })), { max: 5 });
  }
  if (calc.typ === "kostenband" && (calc.abschnitte || []).length) {
    charts += `<div class="charttitle">Kostenband je Abschnitt (max, €)</div>` +
      chartBars(calc.abschnitte.map(x => ({ label: x.abschnitt, wert: x.kosten_max_eur.toLocaleString("de-DE") })));
  }
  if (calc.typ === "opnv_umlauf") {
    charts += `<div class="charttitle">Betriebskennzahlen</div>` + chartBars([
      { label: "Umlaufzeit (min)", wert: calc.umlaufzeit_min },
      { label: "Fahrzeuge HVZ", wert: calc.fahrzeugbedarf_gesamt },
      { label: "Fahrten/Tag", wert: calc.fahrten_tag },
      { label: "Auslastung (%)", wert: calc.auslastung_pct ?? "n/a" },
    ], { max: Math.max(calc.fahrten_tag || 1, 10) });
  }
  const annahmen = [...(strukturiert.annahmen || []), ...(calc.annahmen || [])];
  const pruef = [...(calc.pruefungen || []), ...(strukturiert.datenluecken || [])];
  const liste = (arr) => arr.length ? `<ul class="miniul">${arr.map(x => `<li>${md(String(x))}</li>`).join("")}</ul>` : "";
  return `
    ${a.fehler ? `<div class="errbox">⚠️ ${esc(a.fehler)}</div>` : ""}
    <div class="ausgrid">
      <div>
        <h4>Rechenkern (deterministisch)</h4>
        ${calc.typ ? `<p class="hint">Typ: <b>${esc(calc.typ)}</b>${a.modell ? ` · Daten extrahiert mit <b>${esc(a.modell)}</b>` : ""}</p>` : `<p class="hint">Keine strukturierten Daten – Export nutzt den Antworttext.</p>`}
        ${charts}
      </div>
      <div>
        ${annahmen.length ? `<h4>Annahmen</h4>${liste(annahmen)}` : ""}
        ${pruef.length ? `<h4>Plausibilitätsprüfung</h4>${liste(pruef)}` : ""}
        ${(strukturiert.quellen || []).length ? `<h4>Quellen („Quelle prüfen“ = ungeprüft)</h4>${liste(strukturiert.quellen)}` : ""}
        ${(strukturiert.naechste_schritte || []).length ? `<h4>Nächste Schritte</h4>${liste(strukturiert.naechste_schritte)}` : ""}
      </div>
    </div>`;
}

async function auswerten() {
  if (!state.conv) return toast("Erst eine Unterhaltung mit Inhalt öffnen");
  const box = $("#auswertungBox");
  const btn = $("#btnAuswertung");
  box.classList.remove("hidden");
  box.innerHTML = `<span class="spin">⏳</span> Modell extrahiert Daten, SusMob rechnet …`;
  btn.disabled = true;
  try {
    const a = await api(`/api/conversations/${state.conv.id}/auswertung`, { method: "POST" });
    box.innerHTML = `<div class="aushead"><h3>📊 Auswertung</h3>
      <button class="btn tiny" id="ausClose">schließen</button></div>` + auswertungHTML(a);
    $("#ausClose").onclick = () => box.classList.add("hidden");
    state.auswertung = a;
    state.conv = await api("/api/conversations/" + state.conv.id);
    renderArtifacts();
  } catch (e) {
    box.innerHTML = `<div class="errbox">⚠️ ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

async function exportieren(fmt) {
  if (!state.conv) return toast("Erst eine Unterhaltung mit Inhalt öffnen");
  const btn = fmt === "xlsx" ? $("#btnXlsx") : $("#btnJson");
  const alt = btn.textContent;
  btn.disabled = true; btn.textContent = "⏳ erzeugt …";
  try {
    const info = await api(`/api/conversations/${state.conv.id}/export/${fmt}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
    if (info.hinweis) toast("Hinweis: " + info.hinweis.slice(0, 120));
    else toast(`${info.filename} erzeugt ✓`);
    state.conv = await api("/api/conversations/" + state.conv.id);
    renderArtifacts();
    window.location.href = info.url;
  } catch (e) {
    toast("Fehler: " + e.message);
  } finally {
    btn.disabled = false; btn.textContent = alt;
  }
}

function renderArtifacts() {
  const box = $("#artifactBox");
  if (!box) return;
  const items = state.conv?.artifacts || [];
  if (!items.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  box.innerHTML = `<span class="label">Dateien:</span>` + items.map(a => `
    <span class="chipfile">${a.kind === "xlsx" ? "📊" : a.kind === "daten" ? "🧮" : "🧾"}
      <a href="/api/artifacts/${a.id}" download>${esc(a.filename)}</a>
      <span class="muted">${fmtBytes(a.size)}</span>
      <span class="x" data-aid="${a.id}" title="Löschen">✕</span></span>`).join("");
  $$("#artifactBox .x").forEach(x => {
    x.onclick = async () => {
      await api("/api/artifacts/" + x.dataset.aid, { method: "DELETE" });
      state.conv.artifacts = state.conv.artifacts.filter(a => a.id !== x.dataset.aid);
      renderArtifacts();
    };
  });
}

/* Druckansicht = PDF-Weg A (Druck-CSS, Plan 4.3) */
async function druckAnsicht() {
  if (!state.conv) return toast("Erst eine Unterhaltung öffnen");
  let a = state.auswertung;
  if (!a || a.__cid !== state.conv.id) {
    try {
      a = await api(`/api/conversations/${state.conv.id}/auswertung`, { method: "POST" });
      a.__cid = state.conv.id;
      state.auswertung = a;
    } catch (e) { a = { berechnet: {}, strukturiert: {}, fehler: e.message }; }
  }
  const calc = a.berechnet || {};
  const letzte = [...(state.conv.messages || [])].reverse().find(m => m.role === "assistant");
  let kennzahlen = "";
  if (calc.typ === "co2_bilanz") {
    kennzahlen = `<table><thead><tr><th>Gruppe</th><th>km/Jahr</th><th>Energie</th><th>Faktor</th><th>t CO₂/a</th><th>Anteil</th></tr></thead><tbody>` +
      calc.gruppen.map(g => `<tr><td>${esc(g.bezeichnung)}</td><td>${g.km_gesamt.toLocaleString("de-DE")}</td>
        <td>${g.energie_menge.toLocaleString("de-DE")} ${esc(g.energie_einheit)}</td>
        <td>${g.emissionsfaktor} ${esc(g.faktor_einheit)}</td><td>${g.t_co2.toFixed(1)}</td><td>${g.anteil_pct.toFixed(1)} %</td></tr>`).join("") +
      `<tr class="sum"><td>Summe</td><td></td><td></td><td></td><td>${calc.summe_t_co2.toFixed(1)}</td><td>100 %</td></tr></tbody></table>`;
  } else if (calc.typ === "massnahmen_priorisierung") {
    kennzahlen = `<table><thead><tr><th>Rang</th><th>Maßnahme</th><th>Score</th><th>Priorität</th><th>Kostenband</th><th>Zeitrahmen</th></tr></thead><tbody>` +
      calc.massnahmen.map(m => `<tr><td>${m.rang}</td><td>${esc(m.name)}</td><td>${m.score}</td><td>${esc(m.prioritaet)}</td>
        <td>${esc(m.kosten_band || "–")}</td><td>${esc(m.zeitrahmen || "–")}</td></tr>`).join("") + `</tbody></table>`;
  } else if (calc.typ === "opnv_umlauf") {
    kennzahlen = `<table><tbody>
      <tr><td>Umlaufzeit</td><td>${calc.umlaufzeit_min} min</td></tr>
      <tr><td>Fahrzeugbedarf (HVZ + Reserve)</td><td>${calc.fahrzeugbedarf_gesamt}</td></tr>
      <tr><td>Fahrten/Tag</td><td>${calc.fahrten_tag}</td></tr>
      <tr><td>Fahrleistung/Jahr</td><td>${Number(calc.km_jahr).toLocaleString("de-DE")} km</td></tr>
      <tr><td>Kostenband</td><td>${Number(calc.kosten_jahr_min).toLocaleString("de-DE")}–${Number(calc.kosten_jahr_max).toLocaleString("de-DE")} €/a</td></tr>
      </tbody></table>`;
  }
  const annahmen = [...(a.strukturiert?.annahmen || []), ...(calc.annahmen || []), ...(calc.pruefungen || [])];
  $("#printArea").innerHTML = `
    <div class="printhead">
      <div><div class="printbrand">SusMob · Kommunales Mobilitätsmanagement</div>
      <h1>${esc(state.tile.name)}</h1>
      <div class="printsub">${esc(state.conv.title)} · Stand ${new Date().toLocaleDateString("de-DE")}</div></div>
      <div class="printlogo">[Briefkopf/Wappen der Kommune]</div>
    </div>
    ${kennzahlen}
    ${(calc.gruppen && calc.gruppen.length) ? chartBars(calc.gruppen.map(g => ({ label: g.bezeichnung, wert: g.t_co2 })), { einheit: " t" }) : ""}
    ${(calc.massnahmen && calc.massnahmen.length) ? chartBars(calc.massnahmen.map(m => ({ label: m.name, wert: m.score })), { max: 5 }) : ""}
    <h2>Ergebnis (Modell-Entwurf)</h2>
    <div class="printmd">${md(letzte ? letzte.content : "")}</div>
    ${annahmen.length ? `<h2>Annahmen &amp; Prüfhinweise</h2><ul>${annahmen.map(x => `<li>${esc(String(x))}</li>`).join("")}</ul>` : ""}
    <p class="printfoot">Zahlen aus dem SusMob-Rechenkern, Text aus dem Modell (${esc(letzte?.model || state.tile.model)}).
    Prüfpflicht: Annahmen, Quellen und Kostenbänder vor Verwendung kontrollieren.</p>`;
  document.body.classList.add("printing");
  window.print();
  setTimeout(() => document.body.classList.remove("printing"), 500);
}

function renderMessages() {
  const area = $("#msgArea");
  const msgs = state.conv?.messages || [];
  if (!msgs.length) { area.innerHTML = ""; return; }
  const meta = (m) => {
    if (m.role !== "assistant" || !m.model) return "";
    const usd = Number(m.cost_usd || 0);
    return `<div class="msgmeta">${esc(m.model)} · ${Number(m.prompt_tokens || 0).toLocaleString("de-DE")}↑ ` +
      `${Number(m.completion_tokens || 0).toLocaleString("de-DE")}↓ Tokens · ` +
      `${usd < 0.001 ? usd.toFixed(6) : usd.toFixed(4)} $ · ${((m.duration_ms || 0) / 1000).toFixed(1)} s</div>`;
  };
  area.innerHTML = msgs.map(m => m.role === "user"
    ? `<div class="msg user">${esc(m.content)}</div>`
    : `<div class="msg bot"><div class="who">🤖 ${esc(state.tile.name)}-Bot</div><div class="body">${md(m.content)}</div>${meta(m)}</div>`
  ).join("");
  area.scrollTop = area.scrollHeight;
}

/* Beispiel-Unterhaltung: Banner zeigen, Eingabe sperren */
function renderExampleBar() {
  const bar = $("#exampleBar");
  if (!bar) return;
  const isEx = !!(state.conv && state.conv.is_example);
  bar.classList.toggle("hidden", !isEx);
  $("#composerBox") && $("#composerBox").classList.toggle("hidden", isEx);
  $("#fileChips") && $("#fileChips").classList.toggle("hidden", isEx);
  if (!isEx) return;
  bar.innerHTML = `
    <span class="badge">📘 Beispiel</span>
    <span class="txt">Gespeicherter Beispiellauf – schreibgeschützt. So sieht ein vollständiger Durchlauf dieser Kachel aus.</span>
    <button class="btn primary" id="takeExample">Als eigene Unterhaltung übernehmen</button>`;
  $("#takeExample").onclick = async () => {
    try {
      const r = await api(`/api/conversations/${state.conv.id}/duplicate`, { method: "POST" });
      await loadConvs(state.tile.id);
      await openConv(r.id);
      toast("Übernommen – jetzt kannst du weiterarbeiten ✓");
      $("#msgInput") && $("#msgInput").focus();
    } catch (e) { toast("Fehler: " + e.message); }
  };
}


function renderFiles() {
  const box = $("#fileChips");
  const files = state.conv?.files || [];
  box.innerHTML = files.map(f => `
    <span class="chip">📄 ${esc(f.filename)} <span style="color:var(--muted)">(${fmtBytes(f.size)})</span>
      ${f.extracted_chars ? `<span class="ok" title="Inhalt extrahiert">✓</span>` : `<span title="Kein Text extrahierbar">·</span>`}
      <span class="x" data-fid="${f.id}" title="Entfernen">✕</span>
    </span>`).join("");
  $$("#fileChips .x").forEach(x => {
    x.onclick = async () => {
      await api(`/api/conversations/${state.conv.id}/files/${x.dataset.fid}`, { method: "DELETE" });
      state.conv.files = state.conv.files.filter(f => f.id !== x.dataset.fid);
      renderFiles();
    };
  });
}

async function onFiles(e) {
  const files = [...e.target.files];
  e.target.value = "";
  if (!state.conv) {
    const r = await api("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tile_id: state.tile.id }) });
    await loadConvs(state.tile.id);
    await openConv(r.id);
  }
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await fetch(`/api/conversations/${state.conv.id}/files`, { method: "POST", body: fd });
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || r.statusText); }
    } catch (err) { toast("Upload fehlgeschlagen: " + err.message); continue; }
  }
  state.conv = await api("/api/conversations/" + state.conv.id);
  renderFiles();
}

async function sendMsg() {
  if (state.busy) return;
  const input = $("#msgInput");
  const text = input.value.trim();
  if (!text) return;
  if (!state.conv) {
    const r = await api("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tile_id: state.tile.id }) });
    await loadConvs(state.tile.id);
    state.conv = await api("/api/conversations/" + r.id);
  }
  input.value = "";
  const area = $("#msgArea");
  const empty = $(".empty", area);
  if (empty) empty.remove();
  const userEl = document.createElement("div");
  userEl.className = "msg user";
  userEl.textContent = text;
  area.appendChild(userEl);
  const botEl = document.createElement("div");
  botEl.className = "msg bot";
  botEl.innerHTML = `<div class="who">🤖 ${esc(state.tile.name)}-Bot</div><div class="body"></div>`;
  area.appendChild(botEl);
  const bodyEl = $(".body", botEl);
  let acc = "";
  area.scrollTop = area.scrollHeight;
  state.busy = true;
  $("#sendBtn").disabled = true;
  try {
    const res = await fetch(`/api/conversations/${state.conv.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    if (!res.ok) {
      let m = res.statusText;
      try { m = (await res.json()).detail || m; } catch { /* ignore */ }
      throw new Error(m);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        let ev = "", data = "";
        for (const line of chunk.split("\n")) {
          if (line.startsWith("event: ")) ev = line.slice(7).trim();
          else if (line.startsWith("data: ")) data = line.slice(6);
        }
        if (!data) continue;
        let o; try { o = JSON.parse(data); } catch { continue; }
        if (ev === "token") {
          acc += o.t;
          bodyEl.innerHTML = md(acc) + '<span class="cursor"></span>';
          area.scrollTop = area.scrollHeight;
        } else if (ev === "notice") {
          const n = document.createElement("div");
          n.className = "fallbacknote";
          n.innerHTML = md(o.t || "");
          botEl.parentNode.insertBefore(n, botEl);
        } else if (ev === "usage") {
          const m = document.createElement("div");
          m.className = "msgmeta";
          const usd = Number(o.cost_usd || 0);
          m.textContent = `${o.model} · ${Number(o.prompt_tokens || 0).toLocaleString("de-DE")}↑ ` +
            `${Number(o.completion_tokens || 0).toLocaleString("de-DE")}↓ Tokens · ` +
            `${usd < 0.001 ? usd.toFixed(6) : usd.toFixed(4)} $ · ${(Number(o.duration_ms || 0) / 1000).toFixed(1)} s`;
          botEl.appendChild(m);
        } else if (ev === "error") {
          botEl.classList.add("err");
          bodyEl.innerHTML = `<p class="errbox">⚠️ ${esc(o.error)}</p>`;
        }
      }
    }
    bodyEl.innerHTML = md(acc);
  } catch (e) {
    botEl.classList.add("err");
    bodyEl.innerHTML = `<p class="errbox">⚠️ ${esc(e.message)}</p>`;
  } finally {
    state.busy = false;
    $("#sendBtn").disabled = false;
    area.scrollTop = area.scrollHeight;
    // Konversation aktualisieren (Titel kann sich geändert haben)
    const r = await api("/api/conversations/" + state.conv.id).catch(() => null);
    if (r) state.conv = r;
    loadConvs(state.tile.id);
  }
}

/* ---------- Standardwerte ---------- */
async function toggleStd() {
  const panel = $("#stdPanel");
  if (!panel.classList.contains("hidden")) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  panel.innerHTML = `<h3>⚙️ Standardwerte für „${esc(state.tile.name)}"</h3>
    <p class="hint">Diese Werte fließen in jeden Chat als „Konfiguration der Kommune" ein und haben Vorrang vor den Standardwerten im System-Prompt.</p>
    <div class="stdgrid" id="stdGrid">Lädt …</div>
    <div style="margin-top:1rem"><button class="btn primary" id="stdSave">Speichern</button></div>`;
  state.std = await api("/api/tiles/" + state.tile.id + "/standardwerte");
  $("#stdGrid").innerHTML = state.std.map(s => `
    <label class="f"><span>${esc(s.label)}${s.unit ? ` <small style="color:var(--muted)">[${esc(s.unit)}]</small>` : ""}</span>
      <input type="text" data-key="${esc(s.key)}" value="${esc(s.value)}" placeholder="${esc(s.default_value || "–")}">
      <small>${esc(s.description)}</small>
    </label>`).join("") || `<p class="hint">Keine Standardwerte hinterlegt.</p>`;
  $("#stdSave").onclick = async () => {
    const values = {};
    $$("#stdGrid input").forEach(i => { values[i.dataset.key] = i.value.trim(); });
    await api("/api/tiles/" + state.tile.id + "/standardwerte", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }),
    });
    toast("Standardwerte gespeichert ✓");
  };
}

/* ---------- Admin ---------- */
async function viewAdmin(tab) {
  navActive("admin");
  const status = await api("/api/admin/status");
  if (status.protected && !state.admin.token) return adminLogin();
  state.admin.tab = tab || state.admin.tab || localStorage.getItem("susmob_admin_tab") || "kacheln";
  view.innerHTML = `<div class="adminhead">
      <h1>⚙️ Administration</h1>
      <p>Prompts &amp; Modelle · Kostenmessung · Modell-Health · Eval · Audit</p>
      <div class="actions">${status.protected ? `<button class="btn ghost" id="logout">Abmelden</button>` : `<span class="okbox" style="font-size:0.8rem">offen (kein ADMIN_PASSWORD)</span>`}</div>
    </div>
    <div class="tabs" id="adminTabs">
      ${[["kacheln", "🧩 Kacheln & Prompts"], ["kosten", "💵 Kosten & Tokens"], ["health", "🩺 Modell-Health"],
         ["eval", "🧪 Eval"], ["audit", "🔍 Audit-Log"]].map(([id, label]) =>
        `<button class="tab ${state.admin.tab === id ? "active" : ""}" data-tab="${id}">${label}</button>`).join("")}
    </div>
    <div class="adminbody">
      <aside class="adminlist" id="adminList">Lädt …</aside>
      <section class="adminmain" id="adminMain"></section>
    </div>`;
  if (status.protected) $("#logout").onclick = () => { localStorage.removeItem("susmob_admin"); state.admin.token = ""; adminLogin(); };
  $$("#adminTabs .tab").forEach(b => b.onclick = () => {
    state.admin.tab = b.dataset.tab;
    localStorage.setItem("susmob_admin_tab", b.dataset.tab);
    viewAdmin(b.dataset.tab);
  });
  if (state.admin.tab === "kosten") return renderAdminKosten();
  if (state.admin.tab === "health") return renderAdminHealth();
  if (state.admin.tab === "eval") return renderAdminEval();
  if (state.admin.tab === "audit") return renderAdminAudit();
  await loadAdminTiles();
}

/* 💵 Kosten & Tokens – Messwerte aus llm_calls (Phase 0) */
async function renderAdminKosten() {
  const main = $("#adminMain");
  if (!state.tiles.length) state.tiles = await api("/api/tiles");
  $("#adminList").innerHTML = `<div class="convs-sub">Auswertung</div>
    <div class="convitem"><span class="t">Zeitraum wird geladen …</span></div>`;
  main.innerHTML = `<div class="card">Lädt …</div>`;
  const u = await api("/api/admin/usage?days=30");
  const g = u.gesamt || {};
  const tileName = (tid) => (state.tiles.find(t => t.id === tid)?.name) || tid;
  const usd = (v) => Number(v || 0) < 0.01 ? Number(v || 0).toFixed(5) + " $" : Number(v || 0).toFixed(3) + " $";
  $("#adminList").innerHTML = `<div class="convs-sub">Zeitraum</div>
      <div class="convitem"><span class="t">Letzte 30 Tage</span></div>
      <div class="convs-sub">Letzte Tage</div>
      ${(u.je_tag || []).slice(0, 10).map(d => `<div class="convitem"><span class="t">${esc(d.tag)}</span>
        <span class="del" style="opacity:1">${d.calls}</span></div>`).join("")}`;
  main.innerHTML = `
    <div class="card">
      <h3>💵 Kosten & Tokens <span class="hint">${esc(u.hinweis || "")}</span></h3>
      <div class="kpis">
        <div class="kpi"><span>Calls</span><b>${g.calls || 0}</b></div>
        <div class="kpi"><span>Tokens gesamt</span><b>${Number(g.total_tokens || 0).toLocaleString("de-DE")}</b></div>
        <div class="kpi"><span>Kosten</span><b>${usd(g.kosten_usd)}</b></div>
        <div class="kpi"><span>Ø Kosten/Chat-Request</span><b>${usd(g.kosten_pro_call_usd)}</b></div>
        <div class="kpi"><span>Ø Dauer</span><b>${(Number(g.dauer_ms || 0) / 1000).toFixed(1)} s</b></div>
        <div class="kpi"><span>Modelle mit Fehlern</span><b>${(u.je_modell || []).filter(m => m.fehler).length}</b></div>
      </div>
      <p class="hint">${(g.anteil_geschaetzt_pct || 0) > 0
        ? `⚠️ ${g.anteil_geschaetzt_pct} % der Calls mussten geschätzt werden (keine usage in der Antwort).`
        : "✓ Alle Calls mit echten OpenRouter-Tokenwerten gemessen."}</p>
    </div>
    <div class="card">
      <h3>Je Kachel</h3>
      <table class="admintable"><thead><tr><th>Kachel</th><th>Calls</th><th>Tokens</th><th>Kosten</th><th>Ø Dauer</th></tr></thead><tbody>
        ${(u.je_kachel || []).map(r => `<tr><td>${esc(tileName(r.tile_id))}</td><td>${r.calls}</td>
          <td>${Number(r.tokens).toLocaleString("de-DE")}</td><td>${usd(r.kosten_usd)}</td>
          <td>${(Number(r.dauer_ms) / 1000).toFixed(1)} s</td></tr>`).join("") || `<tr><td colspan="5">Noch keine Messwerte.</td></tr>`}
      </tbody></table>
    </div>
    <div class="card">
      <h3>Je Modell <span class="hint">Fallbacks = Antwort kam aus der Kette, nicht vom Erstmodell</span></h3>
      <table class="admintable"><thead><tr><th>Modell</th><th>Calls</th><th>Tokens</th><th>Kosten</th><th>Fehler</th><th>Fallbacks</th></tr></thead><tbody>
        ${(u.je_modell || []).map(r => `<tr><td class="monocell">${esc(r.model)}</td><td>${r.calls}</td>
          <td>${Number(r.tokens).toLocaleString("de-DE")}</td><td>${usd(r.kosten_usd)}</td>
          <td>${r.fehler || ""}</td><td>${r.fallbacks || ""}</td></tr>`).join("") || `<tr><td colspan="6">Noch keine Messwerte.</td></tr>`}
      </tbody></table>
      <p class="hint">Gratis-Modelle erzeugen 0 $ Kosten – der Knappheitsfaktor ist das Tageslimit (50 Requests).
        Die Spalte „Calls“ zeigt den Verbrauch, bevor das Limit greift.</p>
    </div>
    <div class="card">
      <h3>Je Funktion</h3>
      <table class="admintable"><thead><tr><th>Funktion</th><th>Calls</th><th>Kosten</th><th>Ø Dauer</th></tr></thead><tbody>
        ${(u.je_feature || []).map(r => `<tr><td>${esc(r.feature)}</td><td>${r.calls}</td>
          <td>${usd(r.kosten_usd)}</td><td>${(Number(r.dauer_ms) / 1000).toFixed(1)} s</td></tr>`).join("") || `<tr><td colspan="4">–</td></tr>`}
      </tbody></table>
    </div>`;
}

/* 🩺 Modell-Health + Fallback-Kette je Kachel (Phase 0) */
async function renderAdminHealth(refresh = 0) {
  const main = $("#adminMain");
  $("#adminList").innerHTML = `<div class="convs-sub">Diagnose</div>
    <div class="convitem"><span class="t">Endpunktliste prüfen</span></div>`;
  main.innerHTML = `<div class="card"><span class="spin">⏳</span> Prüfe Modelle bei OpenRouter … (offline: Ergebnisse aus dem Cache)</div>`;
  let h;
  try {
    h = await api(`/api/admin/health${refresh ? "?refresh=1" : ""}`);
  } catch (e) {
    main.innerHTML = `<div class="card errbox">⚠️ ${esc(e.message)}</div>`;
    return;
  }
  main.innerHTML = `
    <div class="card">
      <h3>🩺 Modell-Health & Fallback-Ketten
        <button class="btn tiny" id="healthRefresh">🔄 jetzt prüfen</button></h3>
      <p class="hint">${esc(h.hinweis || "")} Geprüfte Modelle: ${h.modelle_geprueft}</p>
      ${(h.kacheln || []).map(k => `
        <div class="healthblock">
          <div class="healthhead"><b>${esc(k.name)}</b>
            <span class="${k.kette_ok ? "okbox" : "errbox"}">${k.kette_ok ? "Kette ok" : "Kette prüfen"}</span>
            ${k.empfehlung && !k.folgt_empfehlung ? `<span class="hint">Plan empfiehlt <code>${esc(k.empfehlung)}</code>
              <button class="btn tiny" data-empf="${k.tile_id}" data-modell="${esc(k.empfehlung)}">übernehmen</button></span>`
              : (k.empfehlung ? `<span class="okbox">entspricht der Plan-Empfehlung</span>` : "")}</div>
          <table class="admintable"><thead><tr><th>Rolle</th><th>Modell</th><th>Endpunkte</th><th>Uptime</th>
            <th>Kontext</th><th>Structured</th><th>Bild</th><th>geprüft</th></tr></thead><tbody>
            ${k.kette.map(e => `<tr><td>${esc(e.rolle)}</td><td class="monocell">${esc(e.model)}</td>
              <td class="${e.endpunkte ? "okbox" : "errbox"}">${e.endpunkte}</td>
              <td>${e.uptime ? e.uptime.toFixed(1) + " %" : "–"}</td>
              <td>${e.kontext ? Number(e.kontext).toLocaleString("de-DE") : "–"}</td>
              <td>${e.structured ? "✅" : "–"}</td><td>${e.vision ? "🖼️" : "–"}</td>
              <td>${esc(e.geprueft || "–")}${e.hinweis ? ` <span class="errbox">${esc(e.hinweis)}</span>` : ""}</td></tr>`).join("")}
          </tbody></table>
          <label class="f"><span>Fallback-Kette (eine Modell-ID je Zeile, Reihenfolge = Priorität)</span>
            <textarea id="kette_${k.tile_id}" rows="${k.kette.length}">${esc(k.kette.slice(1).map(e => e.model).join("\n"))}</textarea></label>
          <button class="btn" data-saveket="${k.tile_id}">💾 Kette speichern</button>
        </div>`).join("")}
    </div>`;
  $("#healthRefresh").onclick = () => renderAdminHealth(1);
  $$("[data-empf]").forEach(b => b.onclick = async () => {
    await api(`/api/admin/tiles/${b.dataset.empf}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: b.dataset.modell }),
    });
    toast("Modell auf Plan-Empfehlung umgestellt ✓");
    renderAdminHealth();
  });
  $$("[data-saveket]").forEach(b => b.onclick = async () => {
    const tid = b.dataset.saveket;
    const liste = ($(`#kette_${tid}`).value || "").split("\n").map(s => s.trim()).filter(Boolean);
    await api(`/api/admin/tiles/${tid}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fallback_models: liste }),
    });
    toast("Fallback-Kette gespeichert ✓");
  });
}

/* 🧪 Eval – Testfälle automatisch bewerten (Phase 2) */
async function renderAdminEval() {
  const main = $("#adminMain");
  main.innerHTML = `<div class="card">Lädt …</div>`;
  const tiles = await api("/api/tiles");
  state.tiles = tiles;
  const runs = await api("/api/admin/eval/results?limit=40");
  $("#adminList").innerHTML = `<div class="convs-sub">Eval-Läufe</div>
    ${runs.slice(0, 12).map(r => `<div class="convitem"><span class="t">${esc(r.tile_id)} · ${r.score}/${r.max_score}</span></div>`).join("")
      || `<div class="convs-empty">Noch keine Läufe.</div>`}`;
  const avg = runs.length ? (runs.reduce((s, r) => s + r.score, 0) / runs.reduce((s, r) => s + r.max_score, 0) * 100) : 0;
  main.innerHTML = `
    <div class="card">
      <h3>🧪 Eval-Harness</h3>
      <p class="hint">Jeder Testfall der Kachel läuft gegen das konfigurierte Modell und wird nach festem Schema
        bewertet (Antwort, Tiefe, benannte Annahmen, Zahlen mit Einheit, Struktur, Quellen- bzw. Scheinpräzisions-Check).
        Läuft nur mit Internetzugang zu OpenRouter.</p>
      <div class="row">
        <label class="f"><span>Kachel</span><select id="evalTile">
          ${tiles.map(t => `<option value="${t.id}">${t.emoji} ${esc(t.name)}</option>`).join("")}
        </select></label>
        <label class="f" style="max-width:160px"><span>max. Testfälle</span>
          <input type="number" id="evalLimit" value="1" min="1" max="10"></label>
        <div style="align-self:flex-end"><button class="btn primary" id="evalRun">▶ Lauf starten</button></div>
      </div>
      <div class="result" id="evalResult"></div>
    </div>
    <div class="card">
      <h3>Letzte Ergebnisse <span class="hint">Ø ${avg.toFixed(0)} % Zielerreichung (≥ 83 % = bestanden)</span></h3>
      <table class="admintable"><thead><tr><th>Zeit</th><th>Kachel</th><th>Testfall</th><th>Modell</th><th>Punkte</th><th>Details</th></tr></thead><tbody>
        ${runs.map(r => `<tr><td>${esc(r.created_at)}</td><td>${esc(r.tile_id)}</td><td>${esc(r.test_name)}</td>
          <td class="monocell">${esc(r.model)}</td><td><b>${r.score}/${r.max_score}</b></td>
          <td>${(r.checks || []).map(c => `<span class="${c.ok ? "okbox" : "errbox"}" title="${esc(c.detail || "")}">${c.ok ? "✓" : "✗"} ${esc(c.name)}</span>`).join(" · ")}</td></tr>`).join("")
        || `<tr><td colspan="6">Noch keine Läufe.</td></tr>`}
      </tbody></table>
    </div>`;
  $("#evalRun").onclick = async () => {
    const btn = $("#evalRun");
    btn.disabled = true; btn.innerHTML = `<span class="spin">⏳</span> läuft …`;
    $("#evalResult").innerHTML = "";
    try {
      const r = await api("/api/admin/eval/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tile_id: $("#evalTile").value, limit: Number($("#evalLimit").value) || 1 }),
      });
      $("#evalResult").innerHTML = (r.ergebnisse || []).map(e => `
        <div class="meta">${esc(e.tile_id)} · ${e.punkte}/${e.max_punkte} P (${e.quote_pct} %) · ${e.kosten_usd} $ ·
          ${e.ziel_erreicht ? '<span class="okbox">bestanden</span>' : '<span class="errbox">nicht bestanden</span>'}</div>
        ${(e.testfaelle || []).map(t => `<div><b>${esc(t.test_name)}</b> – ${t.score}/${t.max_score}
          ${(t.checks || []).map(c => `<span class="${c.ok ? "okbox" : "errbox"}">${c.ok ? "✓" : "✗"} ${esc(c.name)}</span>`).join(" ")}
          ${t.error ? `<div class="errbox">${esc(t.error)}</div>` : ""}</div>`).join("")}`).join("");
      toast("Eval-Lauf abgeschlossen ✓");
      renderAdminEval();
    } catch (e) {
      $("#evalResult").innerHTML = `<div class="errbox">⚠️ ${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "▶ Lauf starten";
    }
  };
}

/* 🔍 Audit-Log */
async function renderAdminAudit() {
  const main = $("#adminMain");
  const rows = await api("/api/admin/audit?limit=200");
  $("#adminList").innerHTML = `<div class="convs-sub">Ereignisse</div>
    ${[...new Set(rows.map(r => r.event))].map(e => `<div class="convitem"><span class="t">${esc(e)}</span></div>`).join("")
      || `<div class="convs-empty">Keine Einträge.</div>`}`;
  main.innerHTML = `<div class="card">
    <h3>🔍 Audit-Log <span class="hint">wer hat wann was erzeugt/geändert – Voraussetzung für Kommunen (Phase 0)</span></h3>
    <table class="admintable"><thead><tr><th>Zeit</th><th>Ereignis</th><th>Kachel</th><th>Unterhaltung</th><th>Detail</th></tr></thead><tbody>
      ${rows.map(r => `<tr><td>${esc(r.ts)}</td><td>${esc(r.event)}</td><td>${esc(r.tile_id || "–")}</td>
        <td class="monocell">${esc((r.conversation_id || "–").slice(0, 12))}</td><td>${esc(r.detail)}</td></tr>`).join("")
        || `<tr><td colspan="5">Keine Einträge.</td></tr>`}
    </tbody></table></div>`;
}

function adminLogin() {
  view.innerHTML = `<div class="loginbox card">
    <h3 style="font-size:1.1rem;margin-bottom:0.8rem">🔐 Admin-Bereich</h3>
    <label class="f"><span>Passwort</span><input type="password" id="admPw" placeholder="ADMIN_PASSWORD"></label>
    <button class="btn primary" id="admGo" style="width:100%">Anmelden</button>
    <p class="errbox" id="admErr" style="margin-top:0.6rem"></p>
  </div>`;
  const go = async () => {
    try {
      const r = await api("/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("#admPw").value }) });
      state.admin.token = r.token;
      localStorage.setItem("susmob_admin", r.token);
      viewAdmin();
    } catch (e) { $("#admErr").textContent = e.message; }
  };
  $("#admGo").onclick = go;
  $("#admPw").addEventListener("keydown", e => { if (e.key === "Enter") go(); });
}

async function loadAdminTiles() {
  state.adminTiles = await api("/api/admin/tiles");
  const list = $("#adminList");
  list.innerHTML = state.adminTiles.map(t => `
    <div class="item ${state.adminTile && state.adminTile.id === t.id ? "active" : ""}" data-tid="${t.id}">
      <span>${t.emoji}</span><span>${esc(t.name)}</span>
    </div>`).join("");
  $$("#adminList .item").forEach(el => el.onclick = () => selectAdminTile(el.dataset.tid));
  if (!state.adminTile || !state.adminTiles.find(t => t.id === state.adminTile.id)) {
    state.adminTile = state.adminTiles[0] || null;
  }
  renderAdminMain();
}

async function selectAdminTile(tid) {
  state.adminTile = state.adminTiles.find(t => t.id === tid) || null;
  $$("#adminList .item").forEach(el => el.classList.toggle("active", el.dataset.tid === tid));
  renderAdminMain();
}

async function renderAdminMain() {
  const main = $("#adminMain");
  const t = state.adminTile;
  if (!t) { main.innerHTML = `<div class="card"><p class="hint">Keine Kachel vorhanden.</p></div>`; return; }
  const models = await api("/api/models");
  const versions = await api(`/api/admin/tiles/${t.id}/versions`);
  state.testCases = await api(`/api/admin/tiles/${t.id}/test-cases`);
  let tcActive = state.testCases[0] ? state.testCases[0].id : null;

  main.innerHTML = `
    <div class="card">
      <h3>Modell & Parameter <span style="color:var(--muted);font-weight:400;font-size:0.8rem">${t.emoji} ${esc(t.name)}</span></h3>
      <div class="row">
        <label class="f"><span>Modell (OpenRouter) <button class="btn tiny" id="reloadModels" type="button" title="Liste live von OpenRouter neu laden">🔄 gratis/aktuell</button></span>
          <select id="modelSel">
            ${models.map(m => `<option value="${esc(m.id)}" ${m.id === t.model ? "selected" : ""}>${esc(m.label)}</option>`).join("")}
            ${models.some(m => m.id === t.model) ? "" : `<option value="${esc(t.model)}" selected>${esc(t.model)} (eigener)</option>`}
          </select>
        </label>
        <label class="f" style="max-width:260px"><span>Temperature: <b id="tempVal">${t.temperature}</b></span>
          <input type="range" id="tempRange" min="0" max="1" step="0.05" value="${t.temperature}">
        </label>
        <div style="align-self:flex-end"><button class="btn primary" id="saveMeta">💾 Speichern</button></div>
      </div>
      <label class="f"><span>Fallback-Kette (Phase 0) – eine Modell-ID je Zeile; wird bei Ausfall/429/fehlendem
        Endpunkt automatisch genutzt</span>
        <textarea id="ketteEdit" rows="3" class="mono">${esc((t.fallback_models || "").replace(/^\[|\]$/g, "").split(",").map(x => x.replace(/^\s*"|"\s*$/g, "")).filter(x => x.trim()).join("\n"))}</textarea>
        <small>Leer = Seed-Vorschlag der Kachel. Aktuell aktiv:
          ${esc((t.fallback_models || "").trim() ? "eigene Kette" : "Seed-Vorschlag")}</small>
      </label>
      <div id="healthLine" class="hint">Health: <a href="#/admin">🩺 Modell-Health</a> prüfen</div>
    </div>
    <div class="card">
      <h3>System-Prompt <span style="color:var(--muted);font-weight:400;font-size:0.78rem">Fachlichkeit, Fallback-Werte, Ausgabestruktur</span></h3>
      <textarea id="promptArea" class="mono" rows="16">${esc(t.system_prompt)}</textarea>
      <div style="display:flex;gap:0.6rem;margin-top:0.7rem;align-items:center">
        <button class="btn primary" id="savePrompt">💾 Prompt speichern</button>
        <span class="hint" style="color:var(--muted);font-size:0.75rem">Letzte Änderung: ${esc(t.prompt_updated_at || "–")} · Speichern erzeugt eine Version</span>
      </div>
      <div class="versions">
        <h4>Versionshistorie</h4>
        <ul>${versions.map(v => `<li><span style="flex:1">v${v.id} · ${esc(v.created_at)} · ${v.chars} Zeichen · ${esc(v.model)}</span>
          <button class="btn" data-vr="${v.id}">♻️ Wiederherstellen</button></li>`).join("") || `<li>Keine Versionen.</li>`}</ul>
      </div>
    </div>
    <div class="card">
      <h3>Testlauf mit Testdaten</h3>
      <div class="testgrid">
        <div>
          <label class="f"><span>Testfall</span>
            <div class="testcase-list" id="tcList">
              ${state.testCases.map(c => `<button class="tc ${c.id === tcActive ? "active" : ""}" data-tcid="${c.id}">${esc(c.name)}<span class="sub">${esc(c.message.slice(0, 80))}</span></button>`).join("") || `<span style="font-size:0.8rem;color:var(--muted)">Keine Testfälle.</span>`}
            </div>
          </label>
          <div style="display:flex;gap:0.5rem">
            <button class="btn" id="tcAdd">+ Testfall anlegen</button>
            <button class="btn danger" id="tcDel">🗑 Löschen</button>
          </div>
        </div>
        <div>
          <label class="f"><span>Test-Nachricht</span><textarea id="testMsg" rows="4"></textarea></label>
          <details style="margin-bottom:0.8rem"><summary style="cursor:pointer;color:var(--muted);font-size:0.85rem;margin-bottom:0.4rem">Dateikontext (simulierter Upload)</summary>
            <textarea id="testFile" class="mono" rows="5" placeholder="z. B. CSV-Zeilen oder Textauszug"></textarea>
          </details>
          <button class="btn primary" id="runTest">▶ Testlauf starten</button>
          <div class="result" id="testResult"></div>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>📘 Beispiel-Unterhaltung dieser Kachel</h3>
      <p class="hint">Erzeugt die Beispielantworten mit dem aktuell konfigurierten Modell
        (<b>${esc(t.model)}</b>) neu – verbraucht so viele OpenRouter-Requests, wie das Beispiel
        Assistenten-Antworten enthält. Beim Free-Tier das Tageslimit (ca. 50 Requests) beachten.</p>
      <button class="btn" id="regenExample">🔁 Beispiel neu erzeugen</button>
      <div class="result" id="exampleResult"></div>
    </div>`;

  const firstTc = state.testCases[0];
  if (firstTc) {
    $("#testMsg").value = firstTc.message;
    $("#testFile").value = firstTc.file_content;
  }
  $$("#tcList .tc").forEach(b => {
    b.onclick = () => {
      const tc = state.testCases.find(c => c.id === +b.dataset.tcid);
      if (!tc) return;
      $("#testMsg").value = tc.message;
      $("#testFile").value = tc.file_content;
      $$("#tcList .tc").forEach(x => x.classList.toggle("active", x === b));
    };
  });

  $("#tempRange").oninput = e => { $("#tempVal").textContent = e.target.value; };
  $("#reloadModels").onclick = async () => {
    try {
      const fresh = await api("/api/models?refresh=1");
      toast(`Modell-Liste aktualisiert: ${fresh.filter(m => m.free).length} gratis von ${fresh.length}`);
      renderAdminMain();
    } catch (e) { toast("Fehler: " + e.message); }
  };
  $("#regenExample").onclick = async () => {
    if (!confirm("Beispiel dieser Kachel mit dem aktuellen Modell neu erzeugen? Das verbraucht OpenRouter-Requests (Free-Tier-Limit beachten).")) return;
    const btn = $("#regenExample");
    btn.disabled = true; btn.textContent = "⏳ läuft …";
    $("#exampleResult").innerHTML = "";
    try {
      const r = await api(`/api/admin/examples/regenerate?tile_id=${encodeURIComponent(t.id)}`, { method: "POST" });
      const res = (r.results || [])[0] || {};
      $("#exampleResult").innerHTML = res.ok
        ? `<div class="meta">✅ Neu erzeugt mit <b>${esc(res.model)}</b> · ${res.chars} Zeichen</div>`
        : `<div class="errbox">⚠️ ${esc(res.error || "Unbekannter Fehler")}</div>`;
    } catch (e) {
      $("#exampleResult").innerHTML = `<div class="errbox">⚠️ ${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "🔁 Beispiel neu erzeugen";
    }
  };
  $("#saveMeta").onclick = async () => {
    const kette = ($("#ketteEdit").value || "").split("\n").map(x => x.trim()).filter(Boolean);
    await api("/api/admin/tiles/" + t.id, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: $("#modelSel").value, temperature: parseFloat($("#tempRange").value),
                             fallback_models: kette }),
    });
    toast("Modell & Parameter gespeichert ✓");
    await loadAdminTiles();
  };
  $("#savePrompt").onclick = async () => {
    await api("/api/admin/tiles/" + t.id, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: $("#promptArea").value }),
    });
    toast("Prompt gespeichert ✓ (neue Version angelegt)");
    await loadAdminTiles();
  };
  $$("#adminMain .versions [data-vr]").forEach(b => {
    b.onclick = async () => {
      if (!confirm("Diese Version als aktuelle übernehmen?")) return;
      await api(`/api/admin/tiles/${t.id}/versions/${b.dataset.vr}/restore`, { method: "POST" });
      toast("Version wiederhergestellt ✓");
      await loadAdminTiles();
    };
  });
  $("#tcAdd").onclick = async () => {
    const name = prompt("Name des Testfalls:");
    if (!name) return;
    await api(`/api/admin/tiles/${t.id}/test-cases`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, message: $("#testMsg").value, file_content: $("#testFile").value }),
    });
    state.testCases = await api(`/api/admin/tiles/${t.id}/test-cases`);
    renderAdminMain();
  };
  $("#tcDel").onclick = async () => {
    const active = $("#tcList .tc.active");
    if (!active) return toast("Kein Testfall ausgewählt");
    if (!confirm("Testfall löschen?")) return;
    await api(`/api/admin/tiles/${t.id}/test-cases/${active.dataset.tcid}`, { method: "DELETE" });
    state.testCases = await api(`/api/admin/tiles/${t.id}/test-cases`);
    renderAdminMain();
  };
  $("#runTest").onclick = async () => {
    const btn = $("#runTest");
    btn.disabled = true; btn.innerHTML = `<span class="spin">⏳</span> Läuft …`;
    $("#testResult").innerHTML = "";
    try {
      const r = await api(`/api/admin/tiles/${t.id}/test`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: $("#testMsg").value, file_content: $("#testFile").value }),
      });
      const u = r.usage || {};
      $("#testResult").innerHTML = `<div class="meta">Modell: <b>${esc(r.model)}</b>${r.fallback ? " (Fallback)" : ""} ·
        ${Number(u.prompt_tokens || 0)}↑ / ${Number(u.completion_tokens || 0)}↓ Tokens ·
        ${Number(u.cost_usd || 0).toFixed(6)} $ · ${((r.dauer_ms || 0) / 1000).toFixed(1)} s · OK</div><pre>${esc(r.content)}</pre>`;
    } catch (e) {
      $("#testResult").innerHTML = `<div class="errbox">⚠️ ${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "▶ Testlauf starten";
    }
  };
}

/* ---------- Init ---------- */
route();
