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
  admin: { token: localStorage.getItem("susmob_admin") || "" },
  adminTiles: [],
  adminTile: null,
  testCases: [],
  rechner: null,
  rechnerRes: null,
  meta: null,
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
  if (h === "#/admin/system") return viewSystem();
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
        ${tile.hat_rechner ? '<button class="btn ghost" id="rechnerToggle">🧮 Rechner</button>' : ""}
        <button class="btn ghost" id="stdToggle">⚙️ Standardwerte</button>
        <button class="btn ghost" id="ergebnisBtn" title="Ergebnisdokument erzeugen und Excel/PDF/CSV exportieren">📊 Ergebnis &amp; Export</button>
        <button class="btn primary" id="newConv">+ Neue Unterhaltung</button>
      </div>
    </div>
    <div id="stdPanel" class="stdpanel hidden"></div>
    <div id="rechnerPanel" class="stdpanel hidden"></div>
    <div class="tilebody">
      <aside class="convs">
        <div class="convs-head">Unterhaltungen</div>
        <div id="convList"></div>
      </aside>
      <section class="chat">
        <div class="examplebar hidden" id="exampleBar"></div>
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
  $("#stdToggle").onclick = () => toggleStd();
  if ($("#rechnerToggle")) $("#rechnerToggle").onclick = () => toggleRechner();
  $("#ergebnisBtn").onclick = () => erzeugeErgebnis();
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
  try { state.conv = await api("/api/conversations/" + cid); }
  catch (e) { return toast("Fehler: " + e.message); }
  state.meta = null;
  $$("#convList .convitem").forEach(el => el.classList.toggle("active", el.dataset.cid === cid));
  renderMessages();
  renderFiles();
  renderExampleBar();
  renderArtefakte();
}

/* ---------- Rechenkern (Phase 2): Zahlen entstehen im Code ---------- */
async function toggleRechner() {
  const panel = $("#rechnerPanel");
  if (!panel.classList.contains("hidden")) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  panel.innerHTML = `<h3>🧮 Rechner – ${esc(state.tile.name)}</h3><p class="hint">Lädt …</p>`;
  let info;
  try { info = await api(`/api/tiles/${state.tile.id}/rechner`); }
  catch (e) { panel.innerHTML = `<p class="errbox">⚠️ ${esc(e.message)}</p>`; return; }
  if (!info.verfuegbar) { panel.innerHTML = `<p class="hint">Für diese Kachel gibt es keinen Rechenkern.</p>`; return; }
  state.rechner = info;
  panel.innerHTML = `<h3>🧮 ${esc(info.name)}</h3>
    <p class="hint">${esc(info.beschreibung)}<br>Die berechneten Zahlen fließen als <b>verbindliche Werte</b> in jeden Chat dieser Kachel ein
    („Rechnen im Code, formulieren im LLM“) – das Modell rechnet nicht selbst.</p>
    <div class="stdgrid" id="rechnerGrid">${info.felder.map(f => `
      <label class="f"><span>${esc(f.label)}${f.unit ? ` <small style="color:var(--muted)">[${esc(f.unit)}]</small>` : ""}</span>
        <input type="text" data-key="${esc(f.key)}" value="${esc(f.wert ?? "")}" placeholder="${esc(f.default ?? "")}">
      </label>`).join("")}</div>
    <div style="margin-top:1rem;display:flex;gap:0.6rem">
      <button class="btn primary" id="rechnerRun">🧮 Berechnen</button>
      <span class="hint" id="rechnerHint" style="align-self:center"></span>
    </div>
    <div id="rechnerOut"></div>`;
  $("#rechnerRun").onclick = runRechner;
}

async function runRechner() {
  const values = {};
  $$("#rechnerGrid input").forEach(i => { values[i.dataset.key] = i.value.trim(); });
  $("#rechnerHint").textContent = "rechnet …";
  try {
    const res = await api(`/api/tiles/${state.tile.id}/rechner`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }),
    });
    state.rechnerRes = res;
    $("#rechnerHint").textContent = "gespeichert – gilt ab jetzt für alle Chats dieser Kachel ✓";
    $("#rechnerOut").innerHTML = rechnerHtml(res);
  } catch (e) {
    $("#rechnerHint").textContent = "";
    $("#rechnerOut").innerHTML = `<p class="errbox">⚠️ ${esc(e.message)}</p>`;
  }
}

function objTable(rows) {
  if (!rows || !rows.length) return "";
  const cols = Object.keys(rows[0]);
  return `<div class="tablewrap"><table><thead><tr>${cols.map(c => `<th>${esc(c.replace(/_/g, " "))}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${esc(r[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function rechnerHtml(res) {
  const skip = new Set(["titel", "tile_id", "rechner", "eingaben", "annahmen", "rechenweg", "quellen", "tabellen"]);
  const scalars = Object.entries(res).filter(([k, v]) => !skip.has(k) && (typeof v === "number" || typeof v === "string"));
  const listen = Object.entries(res).filter(([k, v]) => !skip.has(k) && Array.isArray(v) && v.length && typeof v[0] === "object");
  const dicts = Object.entries(res).filter(([k, v]) => !skip.has(k) && v && typeof v === "object" && !Array.isArray(v));
  let html = "";
  if (scalars.length) html += `<div class="kv">${scalars.map(([k, v]) => `<div><span>${esc(k.replace(/_/g, " "))}</span><b>${esc(v)}</b></div>`).join("")}</div>`;
  for (const [k, v] of dicts) html += `<h4>${esc(k.replace(/_/g, " "))}</h4>${objTable([v])}`;
  for (const [k, v] of listen) html += `<h4>${esc(k.replace(/_/g, " "))}</h4>${objTable(v)}`;
  if (res.rechenweg) html += `<details class="rechenweg"><summary>Rechenweg anzeigen</summary><ul>${res.rechenweg.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>`;
  if (res.annahmen) html += `<details class="rechenweg"><summary>Annahmen (${res.annahmen.length})</summary><ul>${res.annahmen.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>`;
  const exportbar = `<div style="margin-top:0.8rem;display:flex;gap:0.5rem;flex-wrap:wrap">
      <button class="btn tiny" onclick="ergebnisAusRechner()" title="Ergebnisdokument mit diesen Zahlen erzeugen">📊 Als Ergebnisdokument übernehmen</button></div>`;
  return `<div class="rechnerres">${html}${exportbar}</div>`;
}

/* ---------- Ergebnis & Export (Phase 1) ---------- */
function artefaktIcon(kind) {
  return { xlsx: "📊", csv: "🧾", json: "🧩", md: "📝", svg: "📈", html: "🖨️" }[kind] || "📎";
}

function artefaktHtml() {
  const list = (state.conv && state.conv.artifacts) || [];
  if (!list.length) return "";
  return `<div class="artefakte"><div class="arthead">📦 Artefakte aus diesem Chat</div>
    ${list.map(a => `<span class="chip${a.kind === "html" ? " klick" : ""}" data-aid="${a.id}" data-kind="${a.kind}" title="${esc(a.filename)}">
      ${artefaktIcon(a.kind)} ${esc(a.filename)} <span style="color:var(--muted)">(${fmtBytes(a.size)})</span>
      <a class="dl" href="/api/artifacts/${a.id}/download" download>⬇︎</a>
      ${a.kind === "html" ? `<span class="print" data-print="${a.id}">drucken</span>` : ""}
    </span>`).join("")}</div>`;
}

function exportBarHtml() {
  if (!state.conv || state.conv.is_example) return "";
  return `<div class="artefakte exportbar"><div class="arthead">📤 Ergebnisdokument erzeugen &amp; exportieren
      <span class="hint">(Zahlen aus Rechenkern/Ergebnisdokument, nicht aus dem Modelltext)</span></div>
    <span class="chipbtn" onclick="erzeugeErgebnis()">📊 Ergebnis erzeugen</span>
    <span class="chipbtn" onclick="exportiere('xlsx')">📊 Excel</span>
    <span class="chipbtn" onclick="exportiere('csv')">🧾 CSV</span>
    <span class="chipbtn" onclick="exportiere('json')">🧩 JSON</span>
    <span class="chipbtn" onclick="exportiere('md')">📝 Markdown</span>
    <span class="chipbtn" onclick="exportiere('html')">🖨️ PDF (Druckansicht)</span>
  </div>`;
}

function renderArtefakte() {
  const area = $("#msgArea");
  if (!area) return;
  $$(".artefakte", area).forEach(el => el.remove());
  const html = exportBarHtml() + artefaktHtml();
  if (html) area.insertAdjacentHTML("beforeend", html);
  $$("#msgArea .artefakte .print").forEach(el => {
    el.onclick = (e) => { e.preventDefault(); window.open(`/api/artifacts/${el.dataset.print}/anzeige`, "_blank"); };
  });
}

async function erzeugeErgebnis() {
  if (!state.conv) return toast("Bitte zuerst eine Unterhaltung öffnen.");
  if (state.conv.is_example) return toast("Beispiel-Unterhaltung ist schreibgeschützt – bitte übernehmen.");
  const btn = $("#ergebnisBtn");
  if (btn) { btn.disabled = true; btn.textContent = "⏳ erzeuge Ergebnisdokument …"; }
  try {
    const r = await api(`/api/conversations/${state.conv.id}/ergebnis`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "Fasse den Gesprächsstand zum Ergebnisdokument zusammen." }),
    });
    state.conv = await api("/api/conversations/" + state.conv.id);
    renderArtefakte();
    toast(`Ergebnisdokument erzeugt (${r.artifacts.length} Dateien) ✓`);
    if (state.rechnerRes || true) {
      const box = $("#rechnerOut");
      if (box) box.innerHTML = ""; // Panel ggf. zurücksetzen
    }
  } catch (e) {
    toast("Fehler: " + e.message);
    if (String(e.message).includes("schema-konform")) {
      alert("Das Modell hat kein gültiges Ergebnisdokument geliefert." + "\n\n" + e.message);
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "📊 Ergebnis & Export"; }
  }
}

async function ergebnisAusRechner() {
  await erzeugeErgebnis();
}

async function exportiere(format) {
  if (!state.conv) return toast("Keine Unterhaltung geöffnet.");
  try {
    const a = await api(`/api/conversations/${state.conv.id}/export?format=${format}`, { method: "POST" });
    window.open(`/api/artifacts/${a.id}/download`, "_blank");
    state.conv = await api("/api/conversations/" + state.conv.id);
    renderArtefakte();
    toast(`${a.kind.toUpperCase()} erzeugt ✓`);
  } catch (e) { toast("Fehler: " + e.message); }
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

function renderMessages() {
  const area = $("#msgArea");
  const msgs = state.conv?.messages || [];
  if (!msgs.length) { area.innerHTML = ""; return; }
  area.innerHTML = msgs.map(m => m.role === "user"
    ? `<div class="msg user">${esc(m.content)}</div>`
    : `<div class="msg bot"><div class="who">🤖 ${esc(state.tile.name)}-Bot</div><div class="body">${md(m.content)}</div></div>`
  ).join("") + artefaktHtml();
  area.scrollTop = area.scrollHeight;
}

function renderFiles() {
  const box = $("#fileChips");
  const files = state.conv?.files || [];
  box.innerHTML = files.map(f => `
    <span class="chip">${f.kind === "image" ? "🖼️" : "📄"} ${esc(f.filename)} <span style="color:var(--muted)">(${fmtBytes(f.size)})</span>
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
        } else if (ev === "retry") {
          const hint = document.createElement("div");
          hint.className = "retryhint";
          hint.textContent = `⚠️ ${o.model} antwortet nicht – Fallback wird versucht (Wartezeit ${o.wait}s)`;
          botEl.appendChild(hint);
        } else if (ev === "meta") {
          state.meta = o;
          const m = document.createElement("div");
          m.className = "meta";
          m.textContent = `Modell: ${o.model}${o.fallback ? " (Fallback)" : ""} · ${o.tokens} Tokens · ${(o.cost_usd || 0).toFixed(4)} $ · ${(o.duration_ms / 1000).toFixed(1)} s`;
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
async function viewAdmin() {
  navActive("admin");
  const status = await api("/api/admin/status");
  if (status.protected && !state.admin.token) return adminLogin();
  view.innerHTML = `<div class="adminhead">
      <h1>⚙️ System-Prompts & Modelle</h1>
      <p>Pro Kachel: Modell, Fallback-Kette, Temperature, Fach-Prompt, Versionen und Testläufe mit Testdaten.</p>
      <div class="actions">
        <a class="btn ghost" href="#/admin/system" style="text-decoration:none">📈 Kosten, Health &amp; Eval</a>
        ${status.protected ? `<button class="btn ghost" id="logout">Abmelden</button>` : `<span class="okbox" style="font-size:0.8rem">offen (kein ADMIN_PASSWORD)</span>`}
      </div>
    </div>
    <div class="adminbody">
      <aside class="adminlist" id="adminList">Lädt …</aside>
      <section class="adminmain" id="adminMain"></section>
    </div>`;
  if (status.protected) $("#logout").onclick = () => { localStorage.removeItem("susmob_admin"); state.admin.token = ""; adminLogin(); };
  await loadAdminTiles();
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
    await api("/api/admin/tiles/" + t.id, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: $("#modelSel").value, temperature: parseFloat($("#tempRange").value) }),
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
      $("#testResult").innerHTML = `<div class="meta">Modell: <b>${esc(r.model)}</b> · OK</div><pre>${esc(r.content)}</pre>`;
    } catch (e) {
      $("#testResult").innerHTML = `<div class="errbox">⚠️ ${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "▶ Testlauf starten";
    }
  };
}


/* ---------- Admin: Kosten, Health, Audit, Eval (Phase 0/2) ---------- */
async function viewSystem() {
  navActive("admin");
  const status = await api("/api/admin/status");
  if (status.protected && !state.admin.token) return adminLogin();
  view.innerHTML = `<div class="adminhead">
      <h1>📈 Betrieb: Kosten, Health, Audit, Eval</h1>
      <p>Phase 0/2 des Plans: jede Anfrage mit Tokens und Kosten gemessen, Modell-Endpunkte geprüft, Änderungen protokolliert,
      Testfälle automatisch bewertet.</p>
      <div class="actions">
        <a class="btn ghost" href="#/admin" style="text-decoration:none">← Prompts &amp; Modelle</a>
        ${status.protected ? `<button class="btn ghost" id="logout2">Abmelden</button>` : ""}
        <span class="okbox" style="font-size:0.8rem">Modus: ${esc(status.mode || "demo")}</span>
      </div>
    </div>
    <div class="syswrap">
      <div class="card" id="kpiCard">Lädt …</div>
      <div class="card" id="healthCard">Lädt …</div>
      <div class="card" id="tabellenCard">Lädt …</div>
      <div class="card" id="evalCard">Lädt …</div>
      <div class="card" id="auditCard">Lädt …</div>
    </div>`;
  if ($("#logout2")) $("#logout2").onclick = () => { localStorage.removeItem("susmob_admin"); state.admin.token = ""; adminLogin(); };
  await loadSystem();
}

function kpi(label, wert, hint) {
  return `<div class="kpi"><div class="l">${esc(label)}</div><div class="v">${wert}</div>${hint ? `<div class="h">${esc(hint)}</div>` : ""}</div>`;
}

async function loadSystem() {
  let m;
  try { m = await api("/api/admin/metrics?days=30"); }
  catch (e) { $("#kpiCard").innerHTML = `<p class="errbox">⚠️ ${esc(e.message)}</p>`; return; }
  const k = m.kennzahlen || {};
  $("#kpiCard").innerHTML = `<h3>💰 Kosten &amp; Tokens (30 Tage)</h3>
    <div class="kpis">
      ${kpi("Anfragen", m.total.calls, `${m.total.errors} Fehler · ${m.total.fallbacks} Fallbacks`)}
      ${kpi("Tokens (In/Out)", `${(m.total.tokens_in / 1000).toFixed(1)}k / ${(m.total.tokens_out / 1000).toFixed(1)}k`, `${m.total.cached_tokens} aus Cache`)}
      ${kpi("Kosten 30 Tage", `${m.total.cost_usd.toFixed(4)} $`, `gesamt: ${m.all_time.cost_usd.toFixed(4)} $`)}
      ${kpi("Kosten je qualifiziertem Chat", `${(k.kosten_je_chat_usd || 0).toFixed(4)} $`, `${m.qualified_chats} Chats mit ≥ 3 Anfragen`)}
      ${kpi("Fehlerquote", `${k.fehlerquote_prozent} %`, "Ziel < 2 % sichtbare Ausfälle")}
      ${kpi("Fallback-Quote", `${k.fallback_quote_prozent} %`, "Anteil Anfragen mit Ausweichmodell")}
      ${kpi("Ø Dauer", `${m.total.avg_duration_ms} ms`, "je Anfrage")}
      ${kpi("Kosten geschätzt", `${k.kosten_geschaetzt_anteil_prozent} %`, "Anteil ohne echten Preis (Free-Modelle)")}
    </div>`;
  const zeilen = (obj) => Object.entries(obj).map(([name, v]) =>
    `<tr><td>${esc(name)}</td><td>${v.calls}</td><td>${v.tokens_in}</td><td>${v.tokens_out}</td>
     <td>${v.cost_usd.toFixed(4)} $</td><td>${v.errors}</td><td>${v.fallbacks}</td></tr>`).join("");
  $("#tabellenCard").innerHTML = `<h3>📊 Je Kachel</h3>
    <div class="tablewrap"><table><thead><tr><th>Kachel</th><th>Anfragen</th><th>Tokens In</th><th>Tokens Out</th><th>Kosten</th><th>Fehler</th><th>Fallbacks</th></tr></thead>
    <tbody>${zeilen(m.per_tile) || '<tr><td colspan="7">noch keine Daten</td></tr>'}</tbody></table></div>
    <h3>🤖 Je Modell</h3>
    <div class="tablewrap"><table><thead><tr><th>Modell</th><th>Anfragen</th><th>Tokens In</th><th>Tokens Out</th><th>Kosten</th><th>Fehler</th><th>Fallbacks</th></tr></thead>
    <tbody>${zeilen(m.per_model) || '<tr><td colspan="7">noch keine Daten</td></tr>'}</tbody></table></div>`;
  loadHealth();
  loadEval();
  loadAudit();
}

async function loadHealth() {
  let h;
  try { h = await api("/api/admin/health"); }
  catch (e) { $("#healthCard").innerHTML = `<p class="errbox">⚠️ ${esc(e.message)}</p>`; return; }
  const auf = h.summary.online;
  const rows = h.tiles.map(t => `<tr><td>${esc(t.name)}</td>
      <td>${t.chain.map(c => `<span class="pill ${c.ok ? "ok" : (c.checked_at ? "bad" : "unk")}" title="${esc(c.note || "")}">
        ${esc(c.model.replace(":free", ""))}${c.uptime ? ` · ${c.uptime}%` : ""}</span>`).join(" ")}</td></tr>`).join("");
  $("#healthCard").innerHTML = `<h3>🩺 Modell-Health-Check
      <button class="btn tiny" id="healthRun" style="margin-left:0.6rem">Jetzt prüfen</button></h3>
    <p class="hint">Prüft für jede Kachel die Endpunktliste des Hauptmodells und der Fallbacks.
      ${auf === null ? "Noch kein Check gelaufen." : (auf ? "OpenRouter erreichbar." : "⚠️ OpenRouter von diesem Server aus nicht erreichbar – Ergebnisse stammen aus dem letzten Check.")}</p>
    <div class="tablewrap"><table><tbody>${rows}</tbody></table></div>
    <p class="hint">Legende: <span class="pill ok">ok</span> aktive Anbieter · <span class="pill bad">aus</span> kein aktiver Endpunkt · <span class="pill unk">?</span> nicht geprüft</p>`;
  $("#healthRun").onclick = async () => {
    const b = $("#healthRun"); b.disabled = true; b.textContent = "⏳ prüft …";
    try { const r = await api("/api/admin/health/check", { method: "POST" }); toast(`Health-Check fertig: ${r.failures.length} Probleme`); await loadHealth(); }
    catch (e) { toast("Fehler: " + e.message); }
    b.disabled = false; b.textContent = "Jetzt prüfen";
  };
}

async function loadEval() {
  let e;
  try { e = await api("/api/admin/eval"); }
  catch (err) { $("#evalCard").innerHTML = `<p class="errbox">⚠️ ${esc(err.message)}</p>`; return; }
  const tiles = state.tiles.length ? state.tiles : await api("/api/tiles");
  state.tiles = tiles;
  const runs = e.runs.map(r => `<tr><td>${esc(r.ts)}</td><td>${esc(r.tile_id)}</td><td>${esc(r.test_case_name)}</td>
      <td><b class="${r.score >= 80 ? "good" : r.score >= 60 ? "mid" : "bad"}">${r.score}</b></td>
      <td>${esc(r.model)}</td><td>${esc((r.findings || "").slice(0, 120))}</td></tr>`).join("");
  $("#evalCard").innerHTML = `<h3>🧪 Eval-Harness (Phase 2)</h3>
    <p class="hint">Testfälle laufen automatisch gegen das Kachel-Modell und werden nach Plan-Kriterien bewertet:
      Vollständigkeit, markierte Annahmen, <b>keine erfundenen Zahlen</b>, Format. Ziel: ≥ 90 % der Läufe ohne erfundene Zahlen.</p>
    <div class="row">
      <label class="f"><span>Kachel</span><select id="evalTile">
        ${tiles.map(t => `<option value="${esc(t.id)}">${esc(t.emoji + " " + t.name)}</option>`).join("")}
      </select></label>
      <label class="f" style="max-width:140px"><span>Testfälle</span><input type="number" id="evalLimit" value="3" min="1" max="10"></label>
      <div style="align-self:flex-end"><button class="btn primary" id="evalRun">▶ Eval-Lauf starten</button></div>
    </div>
    <div id="evalOut"></div>
    <div class="tablewrap"><table><thead><tr><th>Zeit</th><th>Kachel</th><th>Testfall</th><th>Score</th><th>Modell</th><th>Befunde</th></tr></thead>
    <tbody>${runs || '<tr><td colspan="6">noch keine Läufe</td></tr>'}</tbody></table></div>`;
  $("#evalRun").onclick = async () => {
    const b = $("#evalRun"); b.disabled = true; b.textContent = "⏳ läuft …";
    $("#evalOut").innerHTML = `<p class="hint">läuft – pro Testfall ein OpenRouter-Request (Free-Tier-Limit beachten) …</p>`;
    try {
      const r = await api("/api/admin/eval/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tile_id: $("#evalTile").value, limit: parseInt($("#evalLimit").value || "3", 10) }),
      });
      $("#evalOut").innerHTML = r.results.map(x => x.ok
        ? `<div class="evalrow"><b>${x.score}</b> ${esc(x.testfall)} <span class="hint">${esc(x.model)}${x.unbelegte_zahlen && x.unbelegte_zahlen.length ? " · unbelegt: " + x.unbelegte_zahlen.join(", ") : ""}</span></div>`
        : `<div class="errbox">⚠️ ${esc(x.testfall || "")}: ${esc(x.error || "")}</div>`).join("");
      await loadEval();
    } catch (err) { $("#evalOut").innerHTML = `<p class="errbox">⚠️ ${esc(err.message)}</p>`; }
    b.disabled = false; b.textContent = "▶ Eval-Lauf starten";
  };
}

async function loadAudit() {
  let a;
  try { a = await api("/api/admin/audit?limit=60"); }
  catch (e) { $("#auditCard").innerHTML = `<p class="errbox">⚠️ ${esc(e.message)}</p>`; return; }
  $("#auditCard").innerHTML = `<h3>🧾 Audit-Log</h3>
    <p class="hint">Wer hat wann welches Ergebnis erzeugt – Pflicht für kommunalen Einsatz (Phase 0/4).</p>
    <div class="tablewrap"><table><thead><tr><th>Zeit</th><th>Akteur</th><th>Aktion</th><th>Objekt</th><th>Detail</th></tr></thead>
    <tbody>${a.map(r => `<tr><td>${esc(r.ts)}</td><td>${esc(r.actor)}</td><td>${esc(r.action)}</td>
      <td>${esc(r.object_type)} ${esc(r.object_id).slice(0, 12)}</td><td>${esc((r.detail || "").slice(0, 140))}</td></tr>`).join("")
      || '<tr><td colspan="5">noch keine Einträge</td></tr>'}</tbody></table></div>`;
}

/* ---------- Init ---------- */
route();
