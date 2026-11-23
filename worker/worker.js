/**
 * Narrativ API (Cloudflare Worker).
 *  GET  /data/<path>   -> docs/<path> from the private repo (read with a server-side token, cached 5 min at the edge)
 *  POST /feedback      -> issue in the private repo, label "feedback"
 *  POST /scan          -> issue "scan: SYMBOL", label "scan" (the daily pipeline queues it for Claude research)
 *  GET  /quotes?s=A,B -> delayed quotes (Yahoo chart endpoint, unofficial), 60 s edge cache, max 40 symbols
 *  GET  /health
 *  cron (wrangler.toml [triggers]) -> starts the GitHub daily run on time (GitHub's own schedule often starts hours late)
 * Secrets (wrangler secret): GH_TOKEN (fine-grained: Narrativ contents read, issues write, actions write).
 * Vars: REPO, APP_KEY (sent by the app in X-App-Key; keeps casual traffic out, not a security boundary).
 * Abuse limits on POST /feedback and /scan (no KV / D1 binding exists, so nothing here is a hard guarantee):
 *  - body capped at MAX_BODY bytes, text fields truncated, non-string fields rejected;
 *  - per-IP daily cap (IP_DAILY_CAP) held in isolate memory: best-effort only, it resets when the isolate is evicted and is not
 *    shared between isolates / colos (the Cache API does not persist on workers.dev, so it cannot hold the counter);
 *  - global daily cap (GLOBAL_DAILY_CAP): counts the feedback / scan issues GitHub already holds for the last 24 h, so it is exact
 *    across isolates (GitHub is the shared store); fails open if GitHub's list call fails;
 *  - /scan for a symbol that already has a "scan: SYMBOL" issue (open or closed) created in the last 7 days returns that issue
 *    number with duplicate:true instead of creating another.
 */
const JSON_HDR = { "content-type": "application/json; charset=utf-8" };
// Must equal the second entry of wrangler.toml crons. Cloudflare numbers day-of-week 1 = Sunday, so the schedules use MON-FRI names.
const IPO_CRON = "40 8 * * MON-FRI";
const MAX_BODY = 8 * 1024;
const IP_DAILY_CAP = 10;      // feedback + scan posts per IP per UTC day (best-effort, per isolate)
const GLOBAL_DAILY_CAP = 100; // feedback + scan issues per rolling 24 h, counted from GitHub
const SCAN_DEDUPE_DAYS = 7;
const ipHits = new Map();     // ip -> { day, n }

function bad(status, msg) {
  return new Response(JSON.stringify({ ok: false, error: msg }), { status, headers: JSON_HDR });
}

async function gh(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${env.REPO}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`,
      "user-agent": "narrativ-worker",
      "x-github-api-version": "2022-11-28",
      ...(init.headers || {}),
    },
  });
}

async function issue(env, title, body, labels) {
  const r = await gh(env, "/issues", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/vnd.github+json" },
    body: JSON.stringify({ title: title.slice(0, 120), body, labels }),
  });
  if (!r.ok) return bad(502, `github ${r.status}`);
  const j = await r.json();
  return new Response(JSON.stringify({ ok: true, number: j.number }), { headers: JSON_HDR });
}

function clean(s, n) {
  return String(s ?? "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "").slice(0, n);
}

// User text goes into a GitHub issue: defuse @mentions so a submission cannot notify arbitrary accounts.
function safe(s) {
  return s.replace(/@/g, "@​");
}

// Request body as text, or null when over `max` bytes (Content-Length is advisory, so the stream is counted too).
async function readCapped(req, max) {
  if (Number(req.headers.get("content-length") || 0) > max) return null;
  if (!req.body) return "";
  const reader = req.body.getReader();
  const chunks = [];
  let n = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    n += value.byteLength;
    if (n > max) {
      reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const all = new Uint8Array(n);
  let o = 0;
  for (const c of chunks) {
    all.set(c, o);
    o += c.byteLength;
  }
  return new TextDecoder().decode(all);
}

// Best-effort per-IP daily counter in isolate memory (see header comment).
function ipLimited(req) {
  const ip = req.headers.get("cf-connecting-ip") || "unknown";
  const day = new Date().toISOString().slice(0, 10);
  if (ipHits.size > 5000) for (const [k, v] of ipHits) if (v.day !== day) ipHits.delete(k);
  const h = ipHits.get(ip);
  if (!h || h.day !== day) {
    ipHits.set(ip, { day, n: 1 });
    return false;
  }
  return ++h.n > IP_DAILY_CAP;
}

// Feedback / scan issues created in the last 24 h (up to 300 rows read) against GLOBAL_DAILY_CAP. Fails open.
async function globalCapReached(env) {
  const since = new Date(Date.now() - 864e5).toISOString();
  let n = 0;
  for (let page = 1; page <= 3; page++) {
    const r = await gh(env, `/issues?state=all&since=${since}&per_page=100&page=${page}`);
    if (!r.ok) return false;
    const rows = await r.json();
    for (const x of rows) {
      if (x.pull_request || (x.created_at || "") < since) continue;
      if ((x.labels || []).some((l) => l.name === "feedback" || l.name === "scan")) n++;
    }
    if (rows.length < 100) break;
  }
  return n >= GLOBAL_DAILY_CAP;
}

// Number of an existing "scan: SYMBOL" issue (open or closed) created in the last SCAN_DEDUPE_DAYS days, else null.
// The .NS / .BO suffix is ignored. Fails open.
async function recentScan(env, sym) {
  const since = new Date(Date.now() - SCAN_DEDUPE_DAYS * 864e5).toISOString();
  const base = (s) => s.toUpperCase().replace(/\.(NS|BO)$/, "");
  const want = base(sym);
  for (let page = 1; page <= 3; page++) {
    const r = await gh(env, `/issues?labels=scan&state=all&since=${since}&per_page=100&page=${page}`);
    if (!r.ok) return null;
    const rows = await r.json();
    for (const x of rows) {
      const m = !x.pull_request && (x.created_at || "") >= since && /^scan:\s*(\S+)\s*$/i.exec(x.title || "");
      if (m && base(m[1]) === want) return x.number;
    }
    if (rows.length < 100) break;
  }
  return null;
}

export default {
  async scheduled(event, env, ctx) {
    // 08:40 UTC = 14:10 IST -> IPO subscription update; 11:40 UTC = 17:10 IST -> daily run
    const wf = event.cron === IPO_CRON ? "ipo-pm.yml" : "daily.yml";
    let status = 0, detail = "";
    for (let i = 1; i <= 3; i++) {  // 204 = started; retry transient failures (5xx, network)
      try {
        const r = await gh(env, `/actions/workflows/${wf}/dispatches`, {
          method: "POST",
          headers: { "content-type": "application/json", accept: "application/vnd.github+json" },
          body: JSON.stringify({ ref: "main" }),
        });
        status = r.status;
        if (status === 204) break;
        detail = (await r.text().catch(() => "")).slice(0, 200);
      } catch (e) {
        status = 0;
        detail = String(e).slice(0, 200);
      }
      if (status >= 400 && status < 500) break;  // bad token / missing workflow: retrying will not help
      if (i < 3) await new Promise((res) => setTimeout(res, 3000 * i));
    }
    if (status === 204) {
      console.log(`cron ${event.cron}: ${wf} dispatch -> 204`);
      return;
    }
    // Throwing marks this cron invocation as failed (Cloudflare dashboard: Workers > narrativ > Observability / Cron Events)
    // instead of a console.log nobody reads. The GitHub backup schedule in daily.yml still starts the run later.
    console.error(`cron ${event.cron}: ${wf} dispatch FAILED -> ${status} ${detail}`);
    throw new Error(`cron dispatch of ${wf} failed: ${status} ${detail}`);
  },

  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (url.pathname === "/health") return new Response("ok");
    if (!env.APP_KEY || req.headers.get("x-app-key") !== env.APP_KEY) return bad(401, "app key");

    if (req.method === "GET" && url.pathname === "/feedback/stats") {
      // open / closed counts of in-app feedback issues (feedback #29)
      let open = 0, closed = 0;
      const items = [];
      for (let page = 1; page <= 5; page++) {
        const r = await gh(env, `/issues?labels=feedback&state=all&per_page=100&page=${page}`);
        if (!r.ok) return bad(502, `github ${r.status}`);
        const rows = (await r.json()).filter((x) => !x.pull_request);
        for (const x of rows) {
          x.state === "open" ? open++ : closed++;
          const m = (x.body || "").match(/^\[([^\]]+)\]\s*([^\n]*)/);
          const scr = (x.body || "").match(/screen `([^`]+)`/);
          items.push({ n: x.number, state: x.state, type: m ? m[1] : "Other", text: (m ? m[2] : x.title).slice(0, 200),
                       screen: scr ? scr[1] : "", date: (x.created_at || "").slice(0, 10) });
        }
        if (rows.length < 100) break;
      }
      return new Response(JSON.stringify({ ok: true, open, closed, items }), { headers: JSON_HDR });
    }

    // Delayed quotes for the app (owner's choice A, 20 Nov 2026): up to 40 NSE symbols, from Yahoo's public chart endpoint
    // (unofficial, may be delayed), cached 60 s per symbol at the edge. Only symbols are sent; nothing about the owner.
    if (req.method === "GET" && url.pathname === "/quotes") {
      const syms = (url.searchParams.get("s") || "").split(",").map((x) => x.trim().toUpperCase()).filter((x) => /^[A-Z0-9&\-]{1,20}$/.test(x)).slice(0, 40);
      if (!syms.length) return bad(400, "symbols");
      const cache = caches.default;
      const out = {};
      await Promise.all(syms.map(async (s) => {
        const key = new Request(`https://cache.narrativ/q/${encodeURIComponent(s)}`);
        let r = await cache.match(key);
        if (!r) {
          const y = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(s)}.NS?interval=1d&range=1d`,
            { headers: { "user-agent": "Mozilla/5.0" } }).catch(() => null);
          if (!y || !y.ok) return;
          const m = (((await y.json().catch(() => ({}))).chart || {}).result || [])[0]?.meta;
          if (!m || m.regularMarketPrice == null) return;
          const v = { p: m.regularMarketPrice, prev: m.chartPreviousClose ?? m.previousClose ?? null, t: m.regularMarketTime ?? null };
          r = new Response(JSON.stringify(v), { headers: { ...JSON_HDR, "cache-control": "public, max-age=60" } });
          ctx.waitUntil(cache.put(key, r.clone()));
        }
        out[s] = await r.json();
      }));
      return new Response(JSON.stringify({ ok: true, src: "Yahoo chart (delayed)", quotes: out }), { headers: JSON_HDR });
    }

    if (req.method === "GET" && url.pathname.startsWith("/data/")) {
      // Decode once, then validate the DECODED path: %26 -> & works (M&M.NS, J&KBANK.NS), %2e%2e%2f is seen as ../ and refused.
      // The path is only ever appended under docs/; a second layer of encoding (%25..) leaves a % and fails the whitelist.
      let path;
      try {
        path = decodeURIComponent(url.pathname.slice(6));
      } catch {
        return bad(400, "path");
      }
      if (!/^[\w\-./&]+\.json$/.test(path) || path.startsWith("/")) return bad(400, "path");  // whitelist has no backslash or %
      if (path.split("/").some((seg) => seg === "" || seg === "." || seg === "..")) return bad(400, "path");
      const enc = path.split("/").map(encodeURIComponent).join("/");  // & -> %26 for GitHub and the cache key
      const cache = caches.default;
      const key = new Request(`https://cache.narrativ/${enc}`);
      let res = await cache.match(key);
      if (!res) {
        const r = await gh(env, `/contents/docs/${enc}?ref=main`, { headers: { accept: "application/vnd.github.raw" } });
        if (!r.ok) return bad(r.status === 404 ? 404 : 502, `github ${r.status}`);
        res = new Response(r.body, { headers: { ...JSON_HDR, "cache-control": "public, max-age=300" } });
        ctx.waitUntil(cache.put(key, res.clone()));
      }
      return res;
    }

    if (req.method === "POST" && (url.pathname === "/feedback" || url.pathname === "/scan")) {
      if (ipLimited(req)) return bad(429, "rate limit");
      const raw = await readCapped(req, MAX_BODY);
      if (raw === null) return bad(413, "too large");
      let b;
      try {
        b = JSON.parse(raw);
      } catch {
        return bad(400, "json");
      }
      if (!b || typeof b !== "object" || Array.isArray(b)) return bad(400, "json");
      for (const k of ["version", "screen", "dataDate", "text", "stock", "symbol", "note"]) {
        if (b[k] != null && typeof b[k] !== "string" && typeof b[k] !== "number") return bad(400, `field ${k}`);
      }
      const meta = `\n\n---\nApp ${clean(b.version, 20)} · screen \`${clean(b.screen, 60).replace(/`/g, "'")}\` · data ${clean(b.dataDate, 20)}`;
      if (url.pathname === "/feedback") {
        const text = safe(clean(b.text, 4000).trim());
        if (text.length < 2) return bad(400, "empty");
        const stock = clean(b.stock, 30).replace(/[^\w&.\- ]/g, "");
        const title = `feedback${stock ? ` (${stock})` : ""}: ${text.split("\n")[0].slice(0, 70)}`;
        if (await globalCapReached(env)) return bad(429, "daily limit");
        return issue(env, title, text + meta, ["feedback"]);
      }
      const sym = clean(b.symbol, 30).toUpperCase().trim();
      if (!/^[A-Z0-9&\-]+(\.(NS|BO))?$/.test(sym)) return bad(400, "symbol");
      const dup = await recentScan(env, sym);
      if (dup) return new Response(JSON.stringify({ ok: true, duplicate: true, number: dup }), { headers: JSON_HDR });
      if (await globalCapReached(env)) return bad(429, "daily limit");
      const note = safe(clean(b.note, 1000).trim());
      return issue(env, `scan: ${sym}`, (note || "Requested from the app.") + meta, ["scan"]);
    }
    return bad(404, "not found");
  },
};
