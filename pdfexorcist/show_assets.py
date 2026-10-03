"""Inline CSS and JS for the HTML view."""

CSS = r"""
:root{--bg:#fff;--fg:#1d1d1f;--muted:#5f6368;--line:#d0d4da;--panel:#f6f7f9;--hl:#fff3c4;
--agreed:#009E73;--unresolved:#E69F00;--failed:#D55E00;--skipped:#8a8f98;--engine:#0072B2;--focus:#0072B2;
color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8eaed;--muted:#a0a6ad;--line:#3a3f46;
--panel:#1f2227;--hl:#4a3f12;--engine:#56B4E9;--focus:#56B4E9;--skipped:#9aa0a6}}
*{box-sizing:border-box}
body{margin:0;font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:12px 16px 4px}
h1{font-size:17px;margin:0 0 2px}
.meta{margin:0;color:var(--muted)}
.notes{margin:4px 0 0;padding-left:18px;color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.legend button{display:flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--panel);
color:var(--fg);border-radius:6px;padding:3px 8px;font:inherit;cursor:pointer}
.legend button[aria-pressed=false]{opacity:.45;text-decoration:line-through}
.swatch{width:22px;height:13px;display:inline-block}
.tabs{display:flex;align-items:center;gap:4px;padding:6px 16px;border-bottom:1px solid var(--line);
position:sticky;top:0;background:var(--bg);z-index:5}
.tabs [role=tab]{font:inherit;border:1px solid transparent;background:none;color:var(--fg);padding:5px 12px;
border-radius:6px 6px 0 0;cursor:pointer}
.tabs [role=tab][aria-selected=true]{border-color:var(--line);border-bottom-color:var(--bg);background:var(--panel);font-weight:600}
.zoom{margin-left:auto;display:flex;gap:4px;align-items:center}
.zoom button,.toolbar select,.toolbar input{font:inherit;color:var(--fg);background:var(--panel);
border:1px solid var(--line);border-radius:5px;padding:2px 9px}
.zoom output{min-width:46px;text-align:center;color:var(--muted)}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
main{padding:8px 16px 16px}
.pagewrap{display:flex;gap:12px;align-items:flex-start}
.scroller{overflow:auto;border:1px solid var(--line);border-radius:6px;background:var(--panel);
max-height:calc(100vh - 190px);flex:1;min-width:0}
#detail{width:330px;flex:none;border:1px solid var(--line);border-radius:6px;padding:10px;background:var(--panel);
max-height:calc(100vh - 190px);overflow:auto;position:sticky;top:60px}
@media (max-width:900px){.pagewrap{flex-direction:column}#detail{width:100%;position:static}}
#detail h2{font-size:15px;margin:0 0 4px}
#detail table{border-collapse:collapse;width:100%;margin-top:6px}
#detail td,#detail th{padding:2px 5px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.hint{color:var(--muted);margin:4px 0 8px}
.badge{display:inline-block;padding:0 6px;border-radius:4px;font-weight:600;color:#000}
.b-agreed{background:var(--agreed)}.b-unresolved{background:var(--unresolved)}.b-failed{background:var(--failed)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
svg{display:block}
svg text{font-family:system-ui,sans-serif;fill:var(--fg)}
.cell{vector-effect:non-scaling-stroke;cursor:pointer}
.st-agreed{stroke:var(--agreed);stroke-width:1.5;fill:var(--agreed);fill-opacity:.16}
.st-unresolved{stroke:var(--unresolved);stroke-width:2.5;stroke-dasharray:5 3;fill:url(#p-dots)}
.st-failed{stroke:var(--failed);stroke-width:3;fill:url(#p-hatch)}
.ign{fill:none;stroke:var(--skipped);stroke-width:1;stroke-dasharray:1 2;vector-effect:non-scaling-stroke}
.cell.sel{stroke:var(--focus);stroke-width:4;stroke-dasharray:none}
.hide-agreed .st-agreed,.hide-unresolved .st-unresolved,.hide-failed .st-failed,.hide-skipped .ign{display:none}
.mlabel{fill:var(--fg)}.mlabel.bad{fill:var(--failed);font-weight:700}
.tick{stroke:var(--muted);vector-effect:non-scaling-stroke}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:4px 0 8px}
.toolbar label{display:flex;gap:5px;align-items:center}
.panels{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:10px}
.panel{border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--panel)}
.panel h3{font-size:14px;margin:0;padding:5px 8px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:baseline}
.panel h3 small{color:var(--muted);font-weight:400}
.panel .scroller{border:0;border-radius:0;max-height:62vh}
.r-ok{stroke:var(--engine);stroke-width:1.2;fill:none;vector-effect:non-scaling-stroke}
.r-bad{stroke:var(--failed);stroke-width:3;fill:url(#p-hatch);vector-effect:non-scaling-stroke}
.r-open{stroke:var(--unresolved);stroke-width:2;fill:url(#p-dots);vector-effect:non-scaling-stroke}
.r-borrowed{stroke-dasharray:4 3}
.r-missed{stroke:var(--skipped);stroke-width:1.5;stroke-dasharray:1 3;fill:none;vector-effect:non-scaling-stroke}
.r-text{fill:var(--failed);font-weight:700;paint-order:stroke;stroke:var(--bg);stroke-width:3px}
.only-bad .r-ok,.only-bad .r-missed{display:none}
.tablewrap{overflow:auto;max-height:calc(100vh - 200px);border:1px solid var(--line);border-radius:6px}
#grid{border-collapse:collapse;font-size:13px;min-width:100%}
#grid th,#grid td{padding:3px 8px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:left}
#grid thead th{position:sticky;top:0;background:var(--panel);z-index:1}
#grid thead button{font:inherit;font-weight:600;color:var(--fg);background:none;border:0;padding:0;cursor:pointer}
#grid td.dis{background:var(--hl);font-weight:700}
#grid td.dis::before{content:"\2260 ";color:var(--failed)}
#grid tbody tr{cursor:pointer}
#grid tbody tr:hover td{outline:1px solid var(--line)}
"""

SCRIPT = r"""
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const W = D.image.w, H = D.image.h;
const FS = Math.max(12, Math.round(W / 70));          // margin label size, image px
const ICON = {agreed:"✓", unresolved:"?", failed:"✗", skipped:"·"};
const NAME = {agreed:"agreed", unresolved:"unresolved (engines disagree)", failed:"agreed, fails a check",
              skipped:"text not read as a cell"};
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const keyText = c => Object.entries(c.key).map(([k, v]) => k + "=" + v).join(", ");
const clip = (s, n) => { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
let zoom = 1, selected = -1, pinned = false;

// ---- header -------------------------------------------------------------------
document.getElementById("meta").textContent =
  D.source + ", page " + D.page + ". Engines: " +
  D.engines.map(e => e.name + (e.skipped ? " (skipped)" : " (" + e.readings + ")")).join(", ") +
  ". " + (D.min_agree ? D.min_agree + " must agree." : "A majority must agree.");
const notes = document.getElementById("notes");
D.notes.forEach(n => { const li = document.createElement("li"); li.textContent = n; notes.appendChild(li); });
const SW = {agreed:'<rect x="1" y="1" width="20" height="11" class="st-agreed"/>',
  unresolved:'<rect x="1" y="1" width="20" height="11" class="st-unresolved"/>',
  failed:'<rect x="1" y="1" width="20" height="11" class="st-failed"/>',
  skipped:'<rect x="1" y="1" width="20" height="11" class="ign"/>'};
const legend = document.getElementById("legend");
["agreed","unresolved","failed","skipped"].forEach(s => {
  const b = document.createElement("button");
  b.setAttribute("aria-pressed", "true");
  b.innerHTML = '<svg class="swatch" viewBox="0 0 22 13" aria-hidden="true">' + defs() + SW[s] + '</svg>' +
    '<span aria-hidden="true">' + ICON[s] + '</span> ' + esc(NAME[s]) + ': <b>' + D.counts[s] + '</b>';
  b.title = "Show or hide these boxes";
  b.onclick = () => { const on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", on); document.body.classList.toggle("hide-" + s, !on); };
  legend.appendChild(b);
});

function patterns(){
  return '<defs><pattern id="p-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
    '<rect width="6" height="6" fill="#D55E00" fill-opacity=".12"/><line x1="0" y1="0" x2="0" y2="6" stroke="#D55E00" stroke-width="2.2"/></pattern>' +
    '<pattern id="p-dots" width="6" height="6" patternUnits="userSpaceOnUse">' +
    '<rect width="6" height="6" fill="#E69F00" fill-opacity=".22"/><circle cx="3" cy="3" r="1.3" fill="#E69F00"/></pattern></defs>';
}
// the fill patterns, defined once for every svg on the page
const holder = document.createElement("div");
holder.innerHTML = '<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">' + patterns() + '</svg>';
document.body.prepend(holder.firstChild);
function defs(){ return ""; }
const rect = (b, cls, attrs, title) => '<rect x="' + b[0] + '" y="' + b[1] + '" width="' + Math.max(b[2]-b[0],1) +
  '" height="' + Math.max(b[3]-b[1],1) + '" class="' + cls + '"' + (attrs || "") +
  (title ? '><title>' + esc(title) + '</title></rect>' : '/>');

// ---- page view ----------------------------------------------------------------
const rowW = Math.min(W * 0.45, FS * 0.6 * Math.max(8, ...D.rows.map(r => clip(r.label, 40).length)) + FS);
const colH = FS * 0.5 * Math.max(4, ...D.cols.map(c => clip(c.label, 32).length)) + FS * 1.5;
const VB = [-rowW, -colH, W + rowW + FS, H + colH + FS];
function pageSvg(){
  let s = '<svg id="page-root" viewBox="' + VB.join(" ") + '" role="img" aria-label="Page image with cell boxes">' + defs();
  s += '<image href="' + D.image.src + '" x="0" y="0" width="' + W + '" height="' + H + '"/>';
  D.ignored.forEach(w => { s += rect(w.box, "ign", "", w.text + ": not read as a cell"); });
  D.cells.forEach(c => { if (c.box) s += rect(c.box, "cell st-" + c.status, ' data-i="' + c.i + '"'); });
  D.rows.forEach(r => {
    s += '<line class="tick" x1="' + (-FS*0.4) + '" x2="0" y1="' + r.y + '" y2="' + r.y + '"/>';
    s += '<text class="mlabel" x="' + (-FS*0.6) + '" y="' + r.y + '" font-size="' + FS*0.85 +
      '" text-anchor="end" dominant-baseline="middle">' + esc(clip(r.label, 40)) + '<title>' + esc(r.label) + '</title></text>';
  });
  D.cols.forEach(c => {
    s += '<line class="tick" x1="' + c.x + '" x2="' + c.x + '" y1="' + (-FS*0.4) + '" y2="0"/>';
    s += '<text class="mlabel' + (c.named ? "" : " bad") + '" transform="translate(' + c.x + ',' + (-FS*0.6) +
      ') rotate(-55)" font-size="' + FS*0.85 + '">' + esc(clip(c.label, 32)) + (c.named ? "" : " (no name)") +
      '<title>' + esc(c.label) + '</title></text>';
  });
  return s + '</svg>';
}
const host = document.getElementById("page-svg");
host.innerHTML = pageSvg();
const root = document.getElementById("page-root");
const rects = {};
host.querySelectorAll("rect.cell").forEach(r => { rects[r.dataset.i] = r; });

function detail(i){
  const c = D.cells[i], el = document.getElementById("detail");
  if (!c) { el.innerHTML = '<p class="hint">Hover or click a cell.</p>'; return; }
  let h = '<h2><span class="badge b-' + c.status + '">' + ICON[c.status] + " " + esc(NAME[c.status]) + '</span></h2>';
  h += '<div class="mono">' + esc(keyText(c)) + '</div>';
  Object.entries(c.extra).forEach(([k, v]) => { if (v !== null && v !== "") h += '<div>' + esc(k) + ': <b>' + esc(v) + '</b></div>'; });
  h += '<div>Agreed value: <b class="mono">' + (c.value === "" ? "(none: left blank)" : esc(c.value)) + '</b></div>';
  if (c.failed) h += '<div>Fails: <b>' + esc(c.failed) + '</b></div>';
  h += '<div>Votes: <span class="mono">' + esc(c.votes) + '</span></div>';
  if (!c.box) h += '<div class="hint">No engine gave a position for this cell.</div>';
  h += '<table><thead><tr><th>Engine</th><th>Read</th><th>Position</th></tr></thead><tbody>';
  D.engines.forEach(e => {
    const r = c.readings[e.name];
    if (!r) { h += '<tr><td>' + esc(e.name) + '</td><td class="hint">' + (e.skipped ? "skipped" : "did not read it") + '</td><td></td></tr>'; return; }
    const mark = r.agrees ? "✓" : (c.status === "unresolved" ? "?" : "≠");
    h += '<tr><td>' + esc(e.name) + '</td><td class="mono"><b>' + mark + '</b> ' + esc(r.value) +
      (r.two ? ' <span class="hint">(two readings: no vote)</span>' : "") + '</td><td class="hint">' + esc(r.src || "none") + '</td></tr>';
  });
  el.innerHTML = h + '</tbody></table>';
}
function select(i, pin){
  if (selected >= 0 && rects[selected]) rects[selected].classList.remove("sel");
  selected = i;
  if (pin !== undefined) pinned = pin;
  if (rects[i]) rects[i].classList.add("sel");
  detail(i);
}
function show(i){
  const r = rects[i]; if (!r) return;
  const sc = document.getElementById("page-scroller"), b = D.cells[i].box, k = zoom;
  sc.scrollLeft = (b[0] - VB[0]) * k - sc.clientWidth / 2;
  sc.scrollTop = (b[1] - VB[1]) * k - sc.clientHeight / 2;
}
host.addEventListener("mouseover", ev => { const i = ev.target.dataset && ev.target.dataset.i; if (i !== undefined && !pinned) select(+i); });
host.addEventListener("click", ev => { const i = ev.target.dataset && ev.target.dataset.i; if (i !== undefined) select(+i, true); });
const placed = D.cells.filter(c => c.box);
const ctr = c => [(c.box[0] + c.box[2]) / 2, (c.box[1] + c.box[3]) / 2];
host.addEventListener("keydown", ev => {
  const dirs = {ArrowRight:[1,0], ArrowLeft:[-1,0], ArrowDown:[0,1], ArrowUp:[0,-1]};
  if (ev.key === "Enter") { pinned = !pinned; ev.preventDefault(); return; }
  if (ev.key === "u" || ev.key === "U") {
    const next = placed.find(c => c.status === "unresolved" && c.i > selected) || placed.find(c => c.status === "unresolved");
    if (next) { select(next.i, true); show(next.i); } ev.preventDefault(); return;
  }
  const d = dirs[ev.key]; if (!d) return;
  ev.preventDefault();
  if (selected < 0 || !D.cells[selected].box) { if (placed.length) { select(placed[0].i, true); show(placed[0].i); } return; }
  const [x, y] = ctr(D.cells[selected]);
  let best = null, score = Infinity;
  placed.forEach(c => {
    const [cx, cy] = ctr(c), a = (cx - x) * d[0] + (cy - y) * d[1], o = Math.abs((cx - x) * d[1] + (cy - y) * d[0]);
    if (a > 1 && a + 3 * o < score) { score = a + 3 * o; best = c; }
  });
  if (best) { select(best.i, true); show(best.i); }
});

// ---- compare view ---------------------------------------------------------------
const panels = document.getElementById("panels"), toggles = document.getElementById("engine-toggles");
const onlyBad = document.createElement("label");
onlyBad.innerHTML = '<input type="checkbox" id="only-bad"> only disagreements';
const withGeo = D.engines.filter(e => !e.skipped);
function enginePanel(e){
  let s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(e.name) + ' readings">' + defs();
  s += '<image href="' + D.image.src + '" x="0" y="0" width="' + W + '" height="' + H + '"/>';
  let bad = 0, n = 0;
  D.cells.forEach(c => {
    const r = c.readings[e.name];
    if (!r) { if (c.box) s += rect(c.box, "r-missed", "", keyText(c) + ": not read by " + e.name); return; }
    n++;
    const b = r.box; if (!b) return;
    const cls = r.agrees ? "r-ok" : (c.status === "unresolved" ? "r-open" : "r-bad");
    if (!r.agrees) bad++;
    s += rect(b, cls + (r.src === "borrowed" ? " r-borrowed" : ""), ' data-i="' + c.i + '"', keyText(c) +
      ": " + e.name + " read " + r.value + (c.value !== "" ? ", agreed " + c.value : ", unresolved") +
      " (" + r.src + " position)");
    if (!r.agrees) s += '<text class="r-text" x="' + b[0] + '" y="' + (b[1] - 2) + '" font-size="' + Math.max(8, (b[3]-b[1]) * 0.6) + '">' + esc(r.value) + '</text>';
  });
  return {svg: s + '</svg>', bad: bad, n: n};
}
withGeo.forEach((e, k) => {
  const p = enginePanel(e), div = document.createElement("div");
  div.className = "panel"; div.dataset.engine = e.name;
  div.innerHTML = '<h3>' + esc(e.name) + ' <small>' + p.n + ' readings, ' + p.bad + (p.bad === 1 ? ' differs' : ' differ') + ' from the vote' +
    (e.geometry ? "" : ", no positions of its own (borrowed)") + '</small></h3><div class="scroller" tabindex="0" aria-label="' + esc(e.name) + ' panel"><div class="zoomable">' + p.svg + '</div></div>';
  panels.appendChild(div);
  const t = document.createElement("label");
  t.innerHTML = '<input type="checkbox" checked> ' + esc(e.name);
  t.querySelector("input").onchange = ev => { div.hidden = !ev.target.checked; };
  toggles.appendChild(t);
});
toggles.appendChild(onlyBad);
document.getElementById("only-bad").onchange = ev => panels.classList.toggle("only-bad", ev.target.checked);
let syncing = false;
panels.querySelectorAll(".scroller").forEach(sc => sc.addEventListener("scroll", () => {
  if (syncing) return; syncing = true;
  const fx = sc.scrollLeft / Math.max(1, sc.scrollWidth - sc.clientWidth), fy = sc.scrollTop / Math.max(1, sc.scrollHeight - sc.clientHeight);
  panels.querySelectorAll(".scroller").forEach(o => { if (o !== sc) {
    o.scrollLeft = fx * (o.scrollWidth - o.clientWidth); o.scrollTop = fy * (o.scrollHeight - o.clientHeight); } });
  requestAnimationFrame(() => { syncing = false; });
}));
panels.addEventListener("click", ev => { const i = ev.target.dataset && ev.target.dataset.i;
  if (i !== undefined) { tab("page"); select(+i, true); show(+i); } });

// ---- zoom -------------------------------------------------------------------------
function applyZoom(){
  root.style.width = (VB[2] * zoom) + "px";
  panels.querySelectorAll(".zoomable svg").forEach(s => { s.style.width = (W * zoom) + "px"; });
  document.getElementById("zoom-level").textContent = Math.round(zoom * 100) + "%";
}
function fit(){
  const sc = document.getElementById("page-scroller");
  const w = sc.clientWidth || (window.innerWidth - 380);
  zoom = Math.max(0.1, (w - 4) / VB[2]); applyZoom();
}
const setZoom = z => { zoom = Math.min(8, Math.max(0.1, z)); applyZoom(); };
document.getElementById("zoom-in").onclick = () => setZoom(zoom * 1.25);
document.getElementById("zoom-out").onclick = () => setZoom(zoom / 1.25);
document.getElementById("zoom-fit").onclick = fit;
document.addEventListener("keydown", ev => {
  if (ev.target.matches && ev.target.matches("input,select,textarea")) return;
  if (ev.key === "+" || ev.key === "=") setZoom(zoom * 1.25);
  else if (ev.key === "-") setZoom(zoom / 1.25);
  else if (ev.key === "0") fit();
});

// ---- grid view --------------------------------------------------------------------
const keys = D.key, extras = [...new Set(D.cells.flatMap(c => Object.keys(c.extra)))];
const cols = [...keys.map(k => ({id:"k:" + k, name:k, get:c => c.key[k]})),
  ...extras.map(k => ({id:"x:" + k, name:k, get:c => c.extra[k]})),
  {id:"value", name:"agreed", get:c => c.value},
  {id:"status", name:"status", get:c => c.status + (c.failed ? ": " + c.failed : "")},
  ...D.engines.filter(e => !e.skipped).map(e => ({id:"e:" + e.name, name:e.name, engine:e.name,
     get:c => c.readings[e.name] ? c.readings[e.name].value : "(not read)"}))];
let sortBy = null, sortDir = 1;
const thead = document.querySelector("#grid thead"), tbody = document.querySelector("#grid tbody");
function head(){
  thead.innerHTML = "<tr>" + cols.map(c => '<th aria-sort="' + (sortBy === c.id ? (sortDir > 0 ? "ascending" : "descending") : "none") +
    '"><button data-c="' + esc(c.id) + '">' + esc(c.name) + (sortBy === c.id ? (sortDir > 0 ? " ▲" : " ▼") : "") + '</button></th>').join("") + "</tr>";
}
thead.addEventListener("click", ev => { const id = ev.target.dataset && ev.target.dataset.c; if (!id) return;
  if (sortBy === id) sortDir = -sortDir; else { sortBy = id; sortDir = 1; } grid(); });
const disagrees = c => D.engines.some(e => { const r = c.readings[e.name]; return r && !r.agrees; }) || c.status !== "agreed";
function cmp(a, b){ const x = parseFloat(a), y = parseFloat(b);
  if (!isNaN(x) && !isNaN(y) && String(x) === String(a).trim() && String(y) === String(b).trim()) return x - y;
  return String(a == null ? "" : a).localeCompare(String(b == null ? "" : b), undefined, {numeric:true}); }
function grid(){
  head();
  const f = document.getElementById("grid-filter").value, q = document.getElementById("grid-search").value.toLowerCase();
  let rows = D.cells.filter(c => f === "all" || (f === "disagree" ? disagrees(c) : f === "nobox" ? !c.box : c.status === f));
  if (q) rows = rows.filter(c => cols.some(k => String(k.get(c) == null ? "" : k.get(c)).toLowerCase().includes(q)));
  if (sortBy) { const col = cols.find(c => c.id === sortBy); rows = rows.slice().sort((a, b) => sortDir * cmp(col.get(a), col.get(b))); }
  document.getElementById("grid-count").textContent = rows.length + " of " + D.cells.length + " cells";
  tbody.innerHTML = rows.slice(0, 5000).map(c => '<tr data-i="' + c.i + '" tabindex="0">' + cols.map(k => {
    let cls = "";
    if (k.engine) { const r = c.readings[k.engine]; if (!r || !r.agrees) cls = ' class="dis"'; }
    if (k.id === "status") return '<td><span class="badge b-' + c.status + '">' + ICON[c.status] + '</span> ' + esc(k.get(c)) + '</td>';
    return '<td' + cls + '>' + esc(k.get(c)) + '</td>'; }).join("") + '</tr>').join("");
}
const openRow = ev => { const tr = ev.target.closest("tr"); if (!tr || !tr.dataset.i) return;
  tab("page"); select(+tr.dataset.i, true); show(+tr.dataset.i); };
tbody.addEventListener("click", openRow);
tbody.addEventListener("keydown", ev => { if (ev.key === "Enter") openRow(ev); });
document.getElementById("grid-filter").onchange = grid;
document.getElementById("grid-search").oninput = grid;

// ---- tabs ---------------------------------------------------------------------------
const TABS = ["page", "compare", "grid"];
function tab(name){
  TABS.forEach(t => { const b = document.getElementById("tab-" + t), on = t === name;
    b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
    document.getElementById("view-" + t).hidden = !on; });
  if (name === "grid") grid();
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
}
TABS.forEach((t, k) => { const b = document.getElementById("tab-" + t);
  b.onclick = () => tab(t);
  b.onkeydown = ev => { const d = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
    if (d) { const n = TABS[(k + d + TABS.length) % TABS.length]; tab(n); document.getElementById("tab-" + n).focus(); } }; });
const first = (location.hash || "").slice(1);
tab(TABS.includes(first) ? first : D.start);
fit();
})();
"""
