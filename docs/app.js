"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (v, d = 2) => v == null ? "–" : Number(v).toLocaleString("en-IN", {maximumFractionDigits: d});
const pct = v => v == null ? "–" : `<span class="${v >= 0 ? "up" : "dn"}">${v >= 0 ? "+" : ""}${fmt(v, 1)}%</span>`;
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
const getJSON = (u, d = null) => fetch(u + (u.includes("?") ? "&" : "?") + "t=" + Date.now()).then(r => r.ok ? r.json() : d).catch(() => d);

let DATA = null, THESES = {}, MEMORY = null, FUNNEL = null;
const FILTERS = [
  ["all", "All"], ["BUY ZONE", "Buy zone"], ["WATCH", "Near pivot"], ["PULLBACK", "Pullback"],
  ["early", "Early stage"], ["research", "Researched"], ["star", "★ Watchlist"], ["EXIT", "Exit"],
];
const state = store.get("narrativ-ui2", {filter: "all", sort: "score", q: ""});
const stars = new Set(store.get("narrativ-stars", []));
const save = () => store.set("narrativ-ui2", state);

async function load() {
  [DATA, THESES] = await Promise.all([getJSON("data/picks.json"), getJSON("data/theses.json", {})]);
  THESES = THESES || {};
  const r = DATA.regime || {};
  $("#regime").className = `chip ${r.label === "RISK ON" ? "r-ON" : r.label === "RISK OFF" ? "r-OFF" : "r-CAUTION"}`;
  $("#regime").textContent = `${r.label ?? ""} · breadth ${fmt(r.breadth_pct, 0)}%`;
  route();
}

const statusChip = s => `<span class="chip ${{"BUY ZONE": "s-BUY", WATCH: "s-WATCH", PULLBACK: "s-PULLBACK", EXIT: "s-EXIT", DROPPED: "s-EXIT"}[s] || ""}">${esc(s)}</span>`;
const meter = (l, v) => `<div class="m">${l} ${v ?? "–"}<b><i style="width:${v ?? 0}%"></i></b></div>`;
const meters = p => `<div class="meters six">${meter("Outlook", p.scores.outlook)}${meter("Inflect", p.scores.inflection)}${meter("Undisc", p.scores.undiscovered)}${meter("Value", p.scores.valuation)}${meter("Moment", p.scores.momentum)}${meter("Sentim", p.scores.sentiment)}</div>`;
const nav = active => `<nav class="tabs">${[["", "Picks"], ["upcoming", "Upcoming"], ["memory", "Memory"], ["excluded", "Excluded"]]
  .map(([h, l]) => `<a href="#/${h}" class="${active === h ? "on" : ""}">${l}</a>`).join("")}</nav>`;

function funnelBar() {
  const f = DATA.funnel || {};
  const st = [["Listed", f.universe], ["Companies", f.companies], ["Clean", f.stage0], ["Trend ok", f.stage1], ["Triaged", f.stage2], ["Researched", f.researched]];
  return `<div class="funnel">${st.map(([l, v]) => `<div><b>${fmt(v, 0)}</b><span>${l}</span></div>`).join("<i>›</i>")}</div>`;
}

function signalTags(p) {
  const s = p.signals, t = [];
  if (s.recent_breakout) t.push("Volume breakout");
  if (s.rs_leads) t.push("RS line leading");
  if (s.vcp) t.push("Tight base");
  if (s.slope200_turning) t.push("200DMA turning up");
  if (s.ud_ratio >= 1.3) t.push(`Accumulation ${s.ud_ratio}`);
  if (p.fund.turnaround) t.push("Profit turnaround");
  if ((p.fund.analysts ?? 0) <= 2) t.push("≤2 analysts");
  if (p.research.health === "broken") t.push("⚠ Thesis broken");
  if (p.checkpoints.some(c => c.status === "due")) t.push("Review due");
  return t.concat(p.tags || []);
}

function list() {
  let ps = DATA.picks.slice();
  const f = state.filter, q = state.q.trim().toLowerCase();
  if (f === "early") ps = ps.filter(p => p.stage === "Stage 1→2" || p.stage === "Basing" || (p.stage === "Stage 2" && p.signals.dist200_pct < 25));
  else if (f === "research") ps = ps.filter(p => p.research.has);
  else if (f === "star") ps = ps.filter(p => stars.has(p.symbol));
  else if (f !== "all") ps = ps.filter(p => p.status === f);
  if (q) ps = ps.filter(p => (p.code + " " + p.name + " " + p.industry).toLowerCase().includes(q));
  const key = {score: p => -p.score, outlook: p => -(p.scores.outlook ?? -1), momentum: p => -p.scores.momentum,
    inflection: p => -p.scores.inflection, undiscovered: p => -p.scores.undiscovered, valuation: p => -p.scores.valuation,
    mcap: p => p.fund.mcap_cr ?? 1e9}[state.sort];
  ps.sort((a, b) => key(a) - key(b));
  $("#view").innerHTML = `${nav("")}${funnelBar()}
    <div class="filters">${FILTERS.map(([k, l]) => `<span class="chip ${state.filter === k ? "on" : ""}" data-f="${k}">${l}</span>`).join("")}</div>
    <div class="bar"><input id="q" placeholder="Search symbol, name, industry" value="${esc(state.q)}">
      <select id="sort">${[["score","Score"],["outlook","Outlook"],["inflection","Inflection"],["undiscovered","Undiscovered"],["valuation","Valuation"],["momentum","Momentum"],["mcap","Smallest"]]
        .map(([k, l]) => `<option value="${k}" ${state.sort === k ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div class="pad small muted">${ps.length} shown · data ${esc(DATA.date)}</div>
    <div id="cards">${ps.slice(0, 200).map(card).join("") || `<p class="pad muted">No matches.</p>`}</div>`;
  document.querySelectorAll("[data-f]").forEach(e => e.onclick = () => { state.filter = e.dataset.f; save(); list(); });
  $("#sort").onchange = e => { state.sort = e.target.value; save(); list(); };
  $("#q").oninput = e => { state.q = e.target.value; save(); clearTimeout(window._qt); window._qt = setTimeout(() => {
    const pos = e.target.selectionStart; list(); const i = $("#q"); i.focus(); i.setSelectionRange(pos, pos); }, 350); };
  bindCards();
}
const bindCards = () => document.querySelectorAll("[data-s]").forEach(e => e.onclick = () => location.hash = "#/s/" + encodeURIComponent(e.dataset.s));

function card(p) {
  const b = p.bands;
  return `<div class="card" data-s="${esc(p.symbol)}">
    <div class="row"><div><span class="sym">${stars.has(p.symbol) ? "★ " : ""}${esc(p.code)}</span> <span class="small muted">#${p.rank} · ${p.exch}</span>
      <div class="name">${esc(p.name)} · ${esc(p.industry)}</div></div>
      <div style="text-align:right"><div class="score">${fmt(p.score, 0)}</div>${statusChip(p.status)}</div></div>
    <div class="row small" style="margin-top:6px"><span>₹${fmt(p.price)} ${pct(p.chg_1d)}</span><span>3M ${pct(p.ret_3m)}</span>
      <span class="muted">${esc(p.stage)}</span><span class="muted">₹${fmt(p.fund.mcap_cr, 0)} cr</span></div>
    ${meters(p)}
    <div class="bands"><div><span>${p.status === "BUY ZONE" ? "Buy zone" : "Buy on breakout"}</span>${fmt(b.buy_low, 1)}–${fmt(b.buy_high, 1)}</div><div><span>Stop</span>${fmt(b.stop, 1)} (${b.stop_pct}%)</div><div><span>Target 3R</span>${fmt(b.target, 1)}</div></div>
    ${p.research.thesis ? `<div class="small" style="margin-top:8px">${esc(p.research.thesis)}</div>` : ""}
    <div class="tags">${signalTags(p).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>
  </div>`;
}

const cpRow = c => `<div class="cp cp-${esc(c.status)}"><div class="row"><b>${esc(c.what)}</b><span class="chip">${esc(c.status)}</span></div>
  <div class="small muted">Due ${esc(c.due)}${c.source ? " · " + esc(c.source) : ""}</div>
  ${c.expected ? `<div class="small">Check: ${esc(c.expected)}</div>` : ""}
  ${c.outcome ? `<div class="small">Outcome: ${esc(c.outcome)} ${c.evidence ? `<a href="${esc(c.evidence)}" target="_blank" rel="noopener">source</a>` : ""}</div>` : ""}</div>`;

function sparkline(snaps) {
  const pts = snaps.filter(s => s.score != null).slice(-120);
  if (pts.length < 2) return `<span class="muted small">History builds daily.</span>`;
  const W = 320, H = 60, xs = i => i / (pts.length - 1) * W, ys = v => H - v / 100 * H;
  return `<svg viewBox="0 0 ${W} ${H}" class="spark"><polyline fill="none" stroke="currentColor" stroke-width="2" points="${pts.map((p, i) => `${xs(i).toFixed(1)},${ys(p.score).toFixed(1)}`).join(" ")}"/></svg>
    <div class="row small muted"><span>${esc(pts[0].d)}</span><span>score ${pts.at(-1).score}</span><span>${esc(pts.at(-1).d)}</span></div>`;
}

async function detail(sym) {
  const p = DATA.picks.find(x => x.symbol === sym);
  const mem = await getJSON(`data/stocks/${encodeURIComponent(sym)}.json`);
  const th = THESES[sym];
  if (!p && !mem) { $("#view").innerHTML = `${nav("-")}<p class="pad">Not found.</p>`; return; }
  const li = a => (a && a.length) ? `<ul>${a.map(x => `<li>${esc(typeof x === "string" ? x : `${x.event ?? x.what}${x.timing || x.due ? " (" + (x.timing || x.due) + ")" : ""}`)}</li>`).join("")}</ul>` : `<span class="muted">–</span>`;
  const research = `<h2>Outlook ${th?.updated ? `<span class="small muted">· ${esc(th.updated)} · ${esc(th.source_type ?? "")}</span>` : ""}</h2>
    <div class="box">${th ? `
      <p><b>${esc(th.thesis)}</b></p>
      ${th.guidance ? `<p><span class="muted">Guidance:</span> ${esc(th.guidance)}</p>` : ""}
      ${th.tone ? `<p><span class="muted">Tone vs last call:</span> ${esc(th.tone)}</p>` : ""}
      ${th.sentiment ? `<p><span class="muted">Sentiment:</span> ${esc(th.sentiment)}</p>` : ""}
      <div class="muted small">Catalysts</div>${li(th.catalysts)}
      <div class="muted small">Value-unlock triggers</div>${li(th.unlock_triggers)}
      <div class="muted small">Red flags</div>${li(th.red_flags)}
      ${(th.sources || []).map((u, i) => `<a class="small" href="${esc(u)}" target="_blank" rel="noopener">Source ${i + 1}</a> `).join("")}`
      : `<span class="muted">Not researched yet. Daily Claude research covers the top ${20} and due checkpoints.</span>`}</div>`;
  const cps = mem?.checkpoints?.length ? mem.checkpoints.slice().reverse().map(cpRow).join("") : `<span class="muted small">None yet.</span>`;
  const thist = (mem?.thesis_history || []).slice().reverse().map(t => `<div class="cp"><div class="small muted">${esc(t.updated)} · ${esc(t.quarter ?? "")} · outlook ${t.outlook_score ?? "–"}</div><div class="small">${esc(t.thesis)}</div></div>`).join("");
  const head = p ? `
    <div class="pad" style="padding-top:0"><div class="row"><div><div class="sym" style="font-size:22px">${esc(p.code)} <span class="small muted">${p.exch}</span></div><div class="name" style="max-width:none">${esc(p.name)} · ${esc(p.industry)}</div></div>
      <div style="text-align:right"><div class="score">${fmt(p.score, 0)}</div>${statusChip(p.status)}</div></div>
      <div class="row small" style="margin-top:6px"><span>₹${fmt(p.price)} ${pct(p.chg_1d)}</span><span>3M ${pct(p.ret_3m)}</span><span>6M ${pct(p.ret_6m)}</span><span class="muted">${esc(p.stage)}</span></div>
      ${meters(p)}<div class="small muted" style="margin-top:6px">Thesis health: ${esc(p.research.health)} · quality ${p.quality_pts}/9</div></div>`
    : `<div class="pad"><div class="sym" style="font-size:22px">${esc(sym)}</div><div class="name">${esc(mem.name)}</div>
       <p>${statusChip("DROPPED")} <span class="small">${esc(mem.drop_reason)}</span></p></div>`;
  let body = "";
  if (p) {
    const b = p.bands, f = p.fund, s = p.signals;
    body = `<div id="chart"><p class="pad muted small">Chart available for the top 60 only.</p></div>
    <h2>Entry and exit bands</h2>
    <div class="grid">
      <div><span>Pivot (breakout level)</span>₹${fmt(b.pivot)}</div>
      <div><span>${p.status === "BUY ZONE" ? "Buy zone" : "Buy on breakout"}</span>₹${fmt(b.buy_low)} – ${fmt(b.buy_high)}</div>
      <div><span>Pullback zone (10–21 EMA)</span>₹${fmt(b.pullback_low)} – ${fmt(b.pullback_high)}</div>
      <div><span>Initial stop</span>₹${fmt(b.stop)} (${b.stop_pct}%)</div>
      <div><span>Target (3R, book part)</span>₹${fmt(b.target)}</div>
      <div><span>Trailing stop (3×ATR)</span>₹${fmt(b.trail)}</div>
      <div><span>Exit on close below 50DMA</span>₹${fmt(b.exit_below_sma50)}</div>
      <div><span>Size for 1% risk on ₹10L</span>${b.pivot > b.stop ? fmt(Math.floor(10000 / (b.pivot - b.stop)), 0) + " sh" : "–"}</div>
    </div>
    ${research}
    <h2>Checkpoints</h2><div class="cps">${cps}</div>
    <h2>Score history</h2><div class="box">${sparkline(mem?.snapshots || [])}</div>
    ${thist ? `<h2>Thesis history</h2><div class="cps">${thist}</div>` : ""}
    <h2>Fundamentals</h2>
    <div class="grid">
      <div><span>Market cap</span>₹${fmt(f.mcap_cr, 0)} cr</div>
      <div><span>Revenue YoY (latest Q)</span>${pct(f.rev_yoy_pct)}</div>
      <div><span>Op. margin now / ref Q</span>${fmt(f.opm_pct, 1)}% / ${fmt(f.opm_ref_pct, 1)}%</div>
      <div><span>EBITDA margin</span>${f.ebitda_margin_pct == null ? "–" : fmt(f.ebitda_margin_pct, 1) + "%"}</div>
      <div><span>P/E vs industry</span>${fmt(f.pe, 1)} vs ${fmt(f.ind_pe, 1)}</div>
      <div><span>EV/EBITDA · PEG</span>${fmt(f.ev_ebitda, 1)} · ${fmt(f.peg, 2)}</div>
      <div><span>ROE</span>${f.roe_pct == null ? "–" : fmt(f.roe_pct, 1) + "%"}</div>
      <div><span>Debt / equity</span>${fmt(f.de, 2)}</div>
      <div><span>Capex</span>${esc(f.capex ?? "–")}</div>
      <div><span>Last quarter in data</span>${esc(f.last_quarter ?? "–")}</div>
      <div><span>Analysts</span>${f.analysts ?? "0 / n.a."}</div>
      <div><span>Institutions · insiders</span>${f.inst_pct ?? "–"}% · ${f.insider_pct ?? "–"}%</div>
    </div>
    <h2>Momentum signals</h2>
    <div class="grid">
      <div><span>RS percentile (triaged set)</span>${s.rs_pct}</div>
      <div><span>Up/down volume (50d)</span>${s.ud_ratio}</div>
      <div><span>Distance from 200DMA</span>${s.dist200_pct}%</div>
      <div><span>Traded value / day</span>₹${fmt(s.traded_value_cr, 2)} cr</div>
    </div>
    <div class="tags pad">${signalTags(p).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    ${f.summary ? `<h2>Business</h2><div class="box small">${esc(f.summary)}…</div>` : ""}`;
  } else {
    body = `${research}<h2>Checkpoints</h2><div class="cps">${cps}</div><h2>Score history</h2><div class="box">${sparkline(mem.snapshots || [])}</div>${thist ? `<h2>Thesis history</h2><div class="cps">${thist}</div>` : ""}`;
  }
  const code = p?.code ?? sym.split(".")[0];
  $("#view").innerHTML = `<div class="row"><span class="back" onclick="history.length>1?history.back():location.hash=''">‹ Back</span>
      <span class="back" id="star">${stars.has(sym) ? "★ Watching" : "☆ Watch"}</span></div>${head}${body}
    <div class="pad small"><a href="https://www.screener.in/company/${encodeURIComponent(code)}/" target="_blank" rel="noopener">Screener.in</a> ·
      <a href="https://www.tradingview.com/chart/?symbol=${p?.exch === "BSE" ? "BSE" : "NSE"}:${encodeURIComponent(code)}" target="_blank" rel="noopener">TradingView</a>
      ${p?.fund.website ? ` · <a href="${esc(p.fund.website)}" target="_blank" rel="noopener">Company</a>` : ""}</div>`;
  $("#star").onclick = () => { stars.has(sym) ? stars.delete(sym) : stars.add(sym); store.set("narrativ-stars", [...stars]); detail(sym); };
  window.scrollTo(0, 0);
  if (p) drawChart(sym, p.bands);
}

async function upcoming() {
  MEMORY = MEMORY || await getJSON("data/memory.json", {stocks: []});
  const rows = MEMORY.stocks.flatMap(s => s.checkpoints.map(c => ({...c, symbol: s.symbol, name: s.name, st: s.status})))
    .filter(c => c.st === "active" || THESES[c.symbol]).sort((a, b) => a.due.localeCompare(b.due));
  const due = rows.filter(c => c.status === "due"), open = rows.filter(c => c.status === "open");
  const item = c => `<div class="card" data-s="${esc(c.symbol)}"><div class="row"><span class="sym">${esc(c.symbol.split(".")[0])}</span><span class="chip ${c.status === "due" ? "s-WATCH" : ""}">${esc(c.due)}</span></div>
    <div class="small">${esc(c.what)}</div><div class="small muted">${esc(c.name)}</div></div>`;
  $("#view").innerHTML = `${nav("upcoming")}
    <h2>Review due (${due.length})</h2>${due.map(item).join("") || `<p class="pad muted small">Nothing due.</p>`}
    <h2>Next 45 days</h2>${open.filter(c => (new Date(c.due) - Date.now()) / 864e5 <= 45).map(item).join("") || `<p class="pad muted small">None.</p>`}`;
  bindCards();
}

async function memory() {
  MEMORY = MEMORY || await getJSON("data/memory.json", {stocks: []});
  const dropped = MEMORY.stocks.filter(s => s.status === "dropped").sort((a, b) => (b.last?.d ?? "").localeCompare(a.last?.d ?? ""));
  $("#view").innerHTML = `${nav("memory")}
    <div class="pad small muted">${MEMORY.stocks.length} stocks analysed so far · ${dropped.length} dropped. Every triaged stock keeps its history.</div>
    ${dropped.map(s => `<div class="card" data-s="${esc(s.symbol)}"><div class="row"><span class="sym">${esc(s.symbol.split(".")[0])}</span><span class="small muted">since ${esc(s.first_seen)}</span></div>
      <div class="name" style="max-width:none">${esc(s.name)}</div><div class="small">${esc(s.drop_reason)}</div></div>`).join("") || `<p class="pad muted">No dropped stocks yet.</p>`}`;
  bindCards();
}

async function excluded() {
  FUNNEL = FUNNEL || await getJSON("data/funnel.json", {excluded: [], excluded_by: {}});
  const draw = () => {
    const q = $("#eq").value.trim().toLowerCase();
    const rows = q.length < 2 ? [] : FUNNEL.excluded.filter(e => (e.s + " " + e.n).toLowerCase().includes(q)).slice(0, 60);
    $("#eres").innerHTML = rows.map(e => `<div class="card" style="cursor:default"><div class="row"><span class="sym">${esc(e.s)}</span><span class="small muted">${esc(e.i ?? "")}</span></div>
      <div class="name" style="max-width:none">${esc(e.n)}</div><div class="small">${esc((e.r || []).join("; "))}</div></div>`).join("") || (q.length < 2 ? "" : `<p class="pad muted small">Not found. It may be outside the ₹200 to 20,000 cr band.</p>`);
  };
  $("#view").innerHTML = `${nav("excluded")}
    <div class="pad small muted">Why a stock did not make it. Exclusions today:</div>
    <div class="grid">${Object.entries(FUNNEL.excluded_by).map(([k, v]) => `<div><span>${esc(k)}</span>${v}</div>`).join("")}</div>
    ${FUNNEL.declining_industries?.length ? `<div class="pad small">Declining industries: ${esc(FUNNEL.declining_industries.join(", "))}</div>` : ""}
    <div class="bar" style="margin-top:10px"><input id="eq" placeholder="Search any stock (symbol or name)"></div><div id="eres"></div>`;
  $("#eq").oninput = draw;
}

async function drawChart(sym, b) {
  const d = await getJSON(`data/charts/${encodeURIComponent(sym)}.json`);
  if (!d || !window.LightweightCharts) return;
  const el = $("#chart"); el.innerHTML = "";
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const ch = LightweightCharts.createChart(el, {
    height: 300, width: el.clientWidth,
    layout: {background: {color: dark ? "#181b21" : "#ffffff"}, textColor: dark ? "#98a2b3" : "#667085"},
    grid: {vertLines: {visible: false}, horzLines: {color: dark ? "#2a2f38" : "#eef0f3"}},
    rightPriceScale: {borderVisible: false}, timeScale: {borderVisible: false},
  });
  const c = ch.addCandlestickSeries({upColor: "#16a34a", downColor: "#dc2626", wickUpColor: "#16a34a", wickDownColor: "#dc2626", borderVisible: false});
  c.setData(d.ohlc.map(([t, o, h, l, cl]) => ({time: t, open: o, high: h, low: l, close: cl})));
  const line = (arr, color) => { const s = ch.addLineSeries({color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false});
    s.setData(arr.map((v, i) => v == null ? null : {time: d.ohlc[i][0], value: v}).filter(Boolean)); };
  line(d.sma50, "#60a5fa"); line(d.sma200, "#a78bfa");
  const pl = (price, title, color, style = 2) => c.createPriceLine({price, title, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true});
  pl(b.buy_high, "Buy ≤", "#16a34a"); pl(b.pivot, "Pivot", "#16a34a", 0); pl(b.stop, "Stop", "#dc2626"); pl(b.target, "3R", "#2563eb"); pl(b.trail, "Trail", "#d97706");
  const v = ch.addHistogramSeries({priceScaleId: "", priceFormat: {type: "volume"}, color: dark ? "#3b4252" : "#d0d5dd"});
  ch.priceScale("").applyOptions({scaleMargins: {top: 0.82, bottom: 0}});
  v.setData(d.vol.map((x, i) => ({time: d.ohlc[i][0], value: x})));
  ch.timeScale().setVisibleLogicalRange({from: d.ohlc.length - 130, to: d.ohlc.length});
  addEventListener("resize", () => ch.applyOptions({width: el.clientWidth}));
}

function route() {
  if (!DATA) return;
  const h = location.hash;
  let m;
  if ((m = h.match(/^#\/s\/(.+)/))) return detail(decodeURIComponent(m[1]));
  if (h === "#/upcoming") return upcoming();
  if (h === "#/memory") return memory();
  if (h === "#/excluded") return excluded();
  list();
}
addEventListener("hashchange", route);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
load().catch(e => { $("#view").innerHTML = `<p class="pad">Could not load data: ${esc(e.message)}</p>`; });
