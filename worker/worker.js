/**
 * Narrativ API (Cloudflare Worker).
 *  GET  /data/<path>   -> docs/<path> of the private repo: from R2 (binding DATA_R2, key app/<path>, uploaded by the pipeline
 *                         after each push: narrativ/appsync.py) when R2 is known to be current for that file, else from GitHub
 *                         (read with a server-side token) as before. Held in isolate memory for DATA_TTL_MS (then re-checked
 *                         by ETag with whichever source it came from) and, on a custom domain only, 5 min at the edge.
 *                         Sends an ETag and answers 304 to a matching If-None-Match (the app sends its copy's ETag).
 *                         Freshness guard (r2State): at most once a minute per isolate, R2's app/_manifest.json commit is
 *                         compared with GitHub main (one sha call, a 304 when main did not move; one compare call when it
 *                         did). Files changed since that commit, files the upload flagged as failed, and everything while
 *                         the check cannot tell (no manifest, compare over 300 files or refused) are read from GitHub.
 *  POST /feedback      -> issue in the private repo, label "feedback"
 *  POST /scan          -> issue "scan: SYMBOL", label "scan" (the daily pipeline queues it for Claude research)
 *  GET  /quotes?s=A,B -> delayed quotes (Yahoo chart endpoint, unofficial), 60 s edge cache, max 40 symbols
 *  GET  /health
 *  cron (wrangler.toml [triggers]) -> starts the GitHub daily run on time (GitHub's own schedule often starts hours late)
 * Secrets (wrangler secret): GH_TOKEN (fine-grained narrativ-runner: Narrativ contents + issues, narrativ-app actions).
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
// Must equal the IPO entries of wrangler.toml crons. Cloudflare numbers day-of-week 1 = Sunday, so the schedules use MON-FRI names.
const IPO_CRONS = ["0 3 * * MON-FRI", "0 10 * * MON-FRI"];
const MAX_BODY = 8 * 1024;
const IP_DAILY_CAP = 10;      // feedback + scan posts per IP per UTC day (best-effort, per isolate)
const GLOBAL_DAILY_CAP = 100; // feedback + scan issues per rolling 24 h, counted from GitHub
const SCAN_DEDUPE_DAYS = 7;
const ipHits = new Map();     // ip -> { day, n }

// /data in isolate memory. The Cache API is a no-op on workers.dev, so without this every /data request went to api.github.com.
// Best-effort like ipHits: per isolate, gone when it is evicted. After DATA_TTL_MS a copy is re-checked with GitHub using its
// ETag (GitHub answers 304 without the body; conditional 304s do not count against the token's rate limit).
const DATA_TTL_MS = 60 * 1000;
const DATA_MEM_BUDGET = 32 * 1024 * 1024; // bytes held across files (an isolate has 128 MB)
const DATA_MEM_MAX_FILE = 4 * 1024 * 1024;
const dataMem = new Map();     // encoded path -> { body: Uint8Array, etag, at, src: "r2" | "gh", r2etag }; Map order = LRU first
let dataMemBytes = 0;
const dataPending = new Map(); // encoded path -> Promise of the one read in flight (concurrent requests share it)

// R2 copy of docs/data (see the header). The state is per isolate like dataMem.
const R2_PREFIX = "app/";
const R2_MANIFEST = "app/_manifest.json";
const FRESH_TTL_MS = 60 * 1000;     // re-check R2 against GitHub main at most this often per isolate
const FRESH_MAX_MS = 3 * 60 * 1000; // a result older than this is waited for; younger, it is used while the re-check runs
let fresh = null;        // { at, mEtag, sha, failed: Set, main, mainEtag, stale: Set of paths | null (null = trust nothing) }
let freshPending = null;

function dataMemSet(enc, e) {
  const old = dataMem.get(enc);
  if (old) {
    dataMem.delete(enc);
    dataMemBytes -= old.body.byteLength;
  }
  if (e.body.byteLength > DATA_MEM_MAX_FILE) return;
  dataMem.set(enc, e);
  dataMemBytes += e.body.byteLength;
  for (const [k, v] of dataMem) {
    if (dataMemBytes <= DATA_MEM_BUDGET) break;
    dataMem.delete(k);
    dataMemBytes -= v.body.byteLength;
  }
}

async function sha256Hex(buf) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
  return Array.from(d.slice(0, 16), (b) => b.toString(16).padStart(2, "0")).join("");
}

// One GitHub read of docs/<enc>: { body, etag, at }, or { status } when GitHub refused. A held copy's ETag goes as If-None-Match.
async function readData(env, enc, held) {
  const headers = { accept: "application/vnd.github.raw" };
  if (held && held.etag) headers["if-none-match"] = held.etag;
  const r = await gh(env, `/contents/docs/${enc}?ref=main`, { headers });
  if (r.status === 304 && held) {
    held.at = Date.now();
    return held;
  }
  if (!r.ok) return { status: r.status };
  const body = new Uint8Array(await r.arrayBuffer());
  // GitHub's ETag is derived from the content; should it ever send none, hash the body instead
  const etag = r.headers.get("etag") || `"${await sha256Hex(body)}"`;
  const e = { body, etag, at: Date.now(), src: "gh" };
  dataMemSet(enc, e);
  return e;
}

// One freshness check (see the header). Never throws for GitHub trouble: when GitHub cannot be asked, R2 is the better copy
// (a GitHub read would fail too), so the last known stale set is kept, or none when the manifest commit changed.
async function checkFresh(env) {
  const prev = fresh;
  const st = { at: Date.now(), mEtag: null, sha: null, failed: new Set(), main: null, mainEtag: null, stale: null };
  const obj = await env.DATA_R2.get(R2_MANIFEST, prev && prev.mEtag ? { onlyIf: { etagDoesNotMatch: prev.mEtag } } : undefined);
  if (obj === null) return st;  // nothing uploaded yet
  if (typeof obj.text === "function") {  // a body: the manifest changed (or the first read)
    const m = JSON.parse(await obj.text());
    st.sha = typeof m.sha === "string" && /^[0-9a-f]{40}$/.test(m.sha) ? m.sha : null;
    st.failed = new Set(Array.isArray(m.failed) ? m.failed : []);
  } else {  // unchanged since prev
    st.sha = prev.sha;
    st.failed = prev.failed;
  }
  st.mEtag = obj.etag;
  if (!st.sha) return st;
  const same = prev && prev.sha === st.sha && prev.stale;  // what the last check found for this manifest commit
  try {
    const h = { accept: "application/vnd.github.sha" };
    if (prev && prev.mainEtag) h["if-none-match"] = prev.mainEtag;
    const r = await gh(env, "/commits/main", { headers: h });
    if (r.status === 304 && prev && prev.main) {
      st.main = prev.main;
      st.mainEtag = prev.mainEtag;
    } else if (r.ok) {
      st.main = (await r.text()).trim();
      st.mainEtag = r.headers.get("etag");
    }
  } catch {
    // network: below
  }
  if (!st.main) {
    st.stale = same ? prev.stale : new Set();
    return st;
  }
  if (st.main === st.sha) {
    st.stale = new Set();
    return st;
  }
  if (same && prev.main === st.main) {
    st.stale = prev.stale;
    return st;
  }
  try {
    const r = await gh(env, `/compare/${st.sha}...${st.main}?per_page=1`, { headers: { accept: "application/vnd.github+json" } });
    if (r.ok) {
      const j = await r.json();
      const files = Array.isArray(j.files) ? j.files : [];
      if ((j.status === "ahead" || j.status === "identical") && files.length < 300) {  // GitHub lists at most 300 files
        st.stale = new Set();
        for (const f of files) {
          for (const n of [f.filename, f.previous_filename]) if (typeof n === "string" && n.startsWith("docs/")) st.stale.add(n.slice(5));
        }
      }
    } else if (r.status >= 500 && same) st.stale = prev.stale;
  } catch {
    if (same) st.stale = prev.stale;
  }
  return st;
}

// The freshness state, or null without an R2 binding. Re-checked at most once per FRESH_TTL_MS; up to FRESH_MAX_MS old it is
// used while the re-check runs in the background.
async function r2State(env, ctx) {
  if (!env.DATA_R2) return null;
  const age = fresh ? Date.now() - fresh.at : Infinity;
  if (age < FRESH_TTL_MS) return fresh;
  if (!freshPending) {
    freshPending = checkFresh(env)
      .then((s) => (fresh = s))
      .catch((err) => {  // R2 itself failed: keep the last state (or trust nothing) and try again in a minute
        console.error(`r2 manifest: ${String(err).slice(0, 200)}`);
        fresh = fresh ? { ...fresh, at: Date.now() } : { at: Date.now(), sha: null, failed: new Set(), stale: null };
        return fresh;
      })
      .finally(() => (freshPending = null));
  }
  if (age < FRESH_MAX_MS) {
    ctx.waitUntil(freshPending);
    return fresh;
  }
  return freshPending;
}

function r2Serves(st, path) {
  return !!(st && st.sha && st.stale && path.startsWith("data/") && !st.stale.has(path) && !st.failed.has(path));
}

// One read of docs/<path>: R2 when the freshness state allows it and R2 has the object, else GitHub (readData).
async function loadData(env, ctx, enc, path, held) {
  const st = await r2State(env, ctx);
  if (r2Serves(st, path)) {
    try {
      const fromR2 = held && held.src === "r2";
      const obj = await env.DATA_R2.get(R2_PREFIX + path, fromR2 ? { onlyIf: { etagDoesNotMatch: held.r2etag } } : undefined);
      if (obj !== null) {
        if (typeof obj.arrayBuffer !== "function") {  // precondition failed: the copy held is current
          held.at = Date.now();
          return held;
        }
        const body = new Uint8Array(await obj.arrayBuffer());
        const e = { body, etag: obj.httpEtag, r2etag: obj.etag, at: Date.now(), src: "r2" };
        dataMemSet(enc, e);
        return e;
      }
    } catch (err) {
      console.error(`r2 ${path}: ${String(err).slice(0, 200)}`);  // R2 failed: GitHub as before
    }
  }
  return readData(env, enc, held && held.src !== "r2" ? held : null);
}

// If-None-Match against our ETag; weak and strong forms compare equal (Cloudflare may weaken an ETag when it compresses).
function etagMatches(header, etag) {
  if (!header || !etag) return false;
  const norm = (t) => t.trim().replace(/^W\//, "");
  return header.split(",").some((t) => t.trim() === "*" || norm(t) === norm(etag));
}

function bad(status, msg) {
  return new Response(JSON.stringify({ ok: false, error: msg }), { status, headers: JSON_HDR });
}

async function gh(env, path, init = {}, repo = env.REPO) {
  return fetch(`https://api.github.com/repos/${repo}${path}`, {
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
    // 03:00 / 10:00 UTC = 08:30 / 15:30 IST -> IPO check; 11:40 UTC = 17:10 IST -> daily run
    const wf = IPO_CRONS.includes(event.cron) ? "ipo.yml" : "daily.yml";
    let status = 0, detail = "";
    for (let i = 1; i <= 3; i++) {  // 204 = started; retry transient failures (5xx, network)
      try {
        // The runs live in the public repo (RUN_REPO); the data stays in REPO.
        const r = await gh(env, `/actions/workflows/${wf}/dispatches`, {
          method: "POST",
          headers: { "content-type": "application/json", accept: "application/vnd.github+json" },
          body: JSON.stringify({ ref: "main" }),
        }, env.RUN_REPO || env.REPO);
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
      const held = dataMem.get(enc);
      if (held) {  // mark as recently used
        dataMem.delete(enc);
        dataMem.set(enc, held);
      }
      let e = held && Date.now() - held.at < DATA_TTL_MS ? held : null;
      if (!e) {
        // edge cache: works only on a custom domain (on workers.dev match() always misses and put() is dropped)
        const cache = caches.default;
        const key = new Request(`https://cache.narrativ/${enc}`);
        const hit = await cache.match(key);
        if (hit) {
          const body = new Uint8Array(await hit.arrayBuffer());
          e = { body, etag: hit.headers.get("etag") || `"${await sha256Hex(body)}"`, at: Date.now() };
        } else {
          let p = dataPending.get(enc);
          if (!p) {
            p = loadData(env, ctx, enc, path, held).finally(() => dataPending.delete(enc));
            dataPending.set(enc, p);
          }
          let got;
          try {
            got = await p;
          } catch {
            got = held || { status: 502 };  // GitHub unreachable: the last copy this isolate holds, if any
          }
          if (got.status) return bad(got.status === 404 ? 404 : 502, `github ${got.status}`);
          e = got;
          const put = new Response(e.body.slice(), { headers: { ...JSON_HDR, "cache-control": "public, max-age=300", etag: e.etag } });
          ctx.waitUntil(cache.put(key, put).catch(() => {}));
        }
      }
      const hdr = { ...JSON_HDR, "cache-control": "public, max-age=300", etag: e.etag };
      if (etagMatches(req.headers.get("if-none-match"), e.etag)) return new Response(null, { status: 304, headers: hdr });
      return new Response(e.body.slice(), { headers: hdr });
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
