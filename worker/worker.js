/**
 * Narrativ API (Cloudflare Worker).
 *  GET  /data/<path>   -> docs/<path> of the private repo: from R2 (binding DATA_R2, key app/<path>, uploaded by the pipeline
 *                         after each push: narrativ/appsync.py) when R2 is known to be current for that file, else from GitHub
 *                         (read with a server-side token) as before. Held in isolate memory for DATA_TTL_MS (then re-checked
 *                         by ETag with whichever source it came from) and, on a custom domain only, 5 min at the edge.
 *                         Sends a content-derived ETag (the same for the R2 and the GitHub copy of the same bytes) and
 *                         answers 304 to a matching If-None-Match (the app sends its copy's ETag).
 *                         Freshness guard (r2State): at most once a minute per isolate, R2's app/_manifest.json commit is
 *                         compared with GitHub main (one sha call, a 304 when main did not move; one compare call when it
 *                         did). Files changed since that commit, files the upload flagged as failed, and everything while
 *                         the check cannot tell (no manifest, compare over 300 files or over 1 MB, or refused) are read
 *                         from GitHub.
 *                         Source branch (data-branch plan): the manifest's "ref" ("main" or "data"; none = DATA_REF, default
 *                         "main") is the branch the generated files come from; the freshness check compares against it and
 *                         GitHub reads use it. Files people and Claude write (MAIN_PATHS) and paths outside data/ always come
 *                         from main and never from R2.
 *  POST /feedback      -> issue in the private repo, label "feedback"
 *  POST /scan          -> issue "scan: SYMBOL", label "scan" (the daily pipeline queues it for Claude research)
 *  GET  /feedback/stats -> open / closed counts and the latest in-app feedback issues
 *  GET  /quotes?s=A,B -> delayed quotes (Yahoo chart endpoint, unofficial), 60 s in isolate memory, max 40 symbols
 *                         (NSE unless the symbol carries .BO); one Yahoo call per symbol, inside the Free plan's 50 subrequests
 *  GET  /ticker        -> Home strip: Nifty 50, Sensex (Yahoo), Gift Nifty near-month future (NSE IX), gold 22K (Abharan)
 *  GET  /health        -> "ok" (the only route without the key)
 *  cron (wrangler.toml [triggers]) -> dispatches daily.yml (17:10 IST), ipo.yml, republish.yml and story.yml in RUN_REPO on
 *                         time (GitHub's own schedules often start hours late). Only the exact cron strings below dispatch;
 *                         an unknown string is logged and does nothing.
 * Secrets (wrangler secret): GH_TOKEN (fine-grained narrativ-runner: Narrativ contents + issues, narrativ-app actions);
 *  APP_KEY (sent by the app in X-App-Key, compared in constant time). The key is the only gate on the private data behind
 *  /data, so it is a secret, not a var; a missing APP_KEY refuses every keyed route.
 * Vars: REPO (the private data repo), RUN_REPO (the public repo whose Actions run the jobs), DATA_REF (branch of the generated
 *  data when the manifest names none: "main" until the data branch is live).
 * Binding: DATA_R2 (R2 bucket narrativ-data: app/<path> copies of docs/, app/_manifest.json, ticker/gold22.json).
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
// Every 30 minutes: "Publish research" (republish.yml), which exits at once when no research run pushed since the last
// publish. GitHub's own */30 schedule fired only every 4-9 hours on 23-26 Nov 2026, so finished research reached the app
// hours late (owner feedback #144).
const REPUBLISH_CRON = "*/30 * * * *";
// 01:00 and 04:00 UTC = 06:30 and 09:30 IST: story.yml (Narrativ sheets). GitHub's own schedule for it skipped both runs on
// 26 Nov 2026, so the Worker starts it too (one cron string: the free plan allows few cron triggers).
const STORY_CRON = "0 1,4 * * *";
// 11:40 UTC = 17:10 IST, after the NSE close: daily.yml
const DAILY_CRON = "40 11 * * MON-FRI";
// Cron strings compared after normalising (spaces, case), so "mon-fri" or a trailing space still matches its job; anything
// else does nothing (audit 26 Nov 2026: every unknown string used to start a full daily run).
const normCron = (c) => String(c || "").trim().replace(/\s+/g, " ").toUpperCase();
const CRON_JOBS = new Map([
  [normCron(DAILY_CRON), "daily.yml"], [normCron(REPUBLISH_CRON), "republish.yml"], [normCron(STORY_CRON), "story.yml"],
  ...IPO_CRONS.map((c) => [normCron(c), "ipo.yml"]),
]);
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
const dataMem = new Map();     // encoded path -> { body: Uint8Array, etag (content), gEtag (GitHub's), at, src: "r2" | "gh", r2etag }; LRU first
let dataMemBytes = 0;
const dataPending = new Map(); // encoded path -> { p, at }: the one read in flight (concurrent requests share it)
// A shared read belongs to the request that started it; if that request is cancelled, its promise may never settle. Each
// waiter therefore waits at most PENDING_WAIT_MS, and an entry older than PENDING_MAX_MS is replaced by a new read.
const PENDING_WAIT_MS = 25 * 1000;
const PENDING_MAX_MS = 20 * 1000;
const NOT_FOUND_TTL_MS = 60 * 1000;
const notFound = new Map();    // encoded path -> time a 404 was seen (each 404 cost a GitHub call)
const quoteMem = new Map();    // Yahoo symbol -> { v, at } (the Cache API does nothing on workers.dev)
const QUOTE_TTL_MS = 60 * 1000;

// `p`, or a rejection after `ms` (timer in the caller's own request).
function within(p, ms) {
  let t;
  return Promise.race([p, new Promise((_, rej) => { t = setTimeout(() => rej(new Error("timeout")), ms); })]).finally(() => clearTimeout(t));
}

// R2 copy of docs/data (see the header). The state is per isolate like dataMem.
const R2_PREFIX = "app/";
const R2_MANIFEST = "app/_manifest.json";
const FRESH_TTL_MS = 60 * 1000;     // re-check R2 against GitHub main at most this often per isolate
const FRESH_MAX_MS = 3 * 60 * 1000; // a result older than this is waited for; younger, it is used while the re-check runs
const COMPARE_MAX_BYTES = 1024 * 1024; // a larger compare response is not parsed (CPU), see checkFresh
let fresh = null;        // { at, mEtag, sha, ref, failed: Set, main, mainEtag, stale: Set of paths | null (null = trust nothing) }
const REFS = new Set(["main", "data"]);
// authored on main (Claude's research, the owner's schedule): read from main, never from R2 or the data branch
const MAIN_PATHS = new Set(["data/theses.json", "data/industry_why.json", "data/schedule.json", "data/lessons.jsonl",
  "data/research_runs.jsonl"]);
function defaultRef(env) {
  return env && REFS.has(env.DATA_REF) ? env.DATA_REF : "main";
}
// GitHub branch for one /data path: main for paths outside data/ and for MAIN_PATHS, else the manifest's branch
function refFor(env, st, path) {
  if (!path.startsWith("data/") || MAIN_PATHS.has(path)) return "main";
  return st && REFS.has(st.ref) ? st.ref : defaultRef(env);
}
let freshPending = null;
let freshPendingAt = 0;

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

// The ETag the app sees: derived from the bytes, so the R2 and GitHub copies of one file share it and a switch of source
// around a publish is a 304, not a second download (cost report 26 Nov 2026). Hashed once per new body (native SHA-256).
async function contentEtag(body) {
  return `"c${await sha256Hex(body)}"`;
}

// One GitHub read of docs/<enc>: { body, etag, at }, or { status } when GitHub refused. A held copy's ETag goes as If-None-Match.
async function readData(env, enc, held, ref = "main") {
  const headers = { accept: "application/vnd.github.raw" };
  // GitHub's own ETag (per branch); the app sees the content ETag
  if (held && held.gEtag && (held.gRef || "main") === ref) headers["if-none-match"] = held.gEtag;
  const r = await gh(env, `/contents/docs/${enc}?ref=${ref}`, { headers });
  if (r.status === 304 && held) {
    held.at = Date.now();
    return held;
  }
  if (!r.ok) return { status: r.status };
  const body = new Uint8Array(await r.arrayBuffer());
  const e = { body, etag: await contentEtag(body), gEtag: r.headers.get("etag"), gRef: ref, at: Date.now(), src: "gh" };
  dataMemSet(enc, e);
  return e;
}

// One freshness check (see the header). Never throws for GitHub trouble. When main cannot be read, the last stale set found
// for this manifest commit is kept; without one the state is "trust nothing" (stale null): files come from GitHub, and from R2
// only when that GitHub read fails (loadData). Until 26 Nov 2026 one failed /commits/main call meant "trust everything" and R2
// served files older than main (audit).
async function checkFresh(env) {
  const prev = fresh;
  const st = { at: Date.now(), mEtag: null, sha: null, ref: defaultRef(env), failed: new Set(), main: null, mainEtag: null, stale: null };
  const obj = await env.DATA_R2.get(R2_MANIFEST, prev && prev.mEtag ? { onlyIf: { etagDoesNotMatch: prev.mEtag } } : undefined);
  if (obj === null) return st;  // nothing uploaded yet
  if (typeof obj.text === "function") {  // a body: the manifest changed (or the first read)
    const m = JSON.parse(await obj.text());
    st.sha = typeof m.sha === "string" && /^[0-9a-f]{40}$/.test(m.sha) ? m.sha : null;
    st.failed = new Set(Array.isArray(m.failed) ? m.failed : []);
    if (REFS.has(m.ref)) st.ref = m.ref;
  } else {  // unchanged since prev
    st.sha = prev.sha;
    st.failed = prev.failed;
    st.ref = prev.ref || st.ref;
  }
  st.mEtag = obj.etag;
  if (!st.sha) return st;
  // `main` / `mainEtag` hold the tip of st.ref; a branch switch starts afresh (nothing of the other branch carries over)
  const sameRef = prev && (prev.ref || "main") === st.ref;
  const same = sameRef && prev.sha === st.sha && prev.stale;  // what the last check found for this manifest commit
  try {
    const h = { accept: "application/vnd.github.sha" };
    if (sameRef && prev.mainEtag) h["if-none-match"] = prev.mainEtag;
    const r = await gh(env, `/commits/${st.ref}`, { headers: h });
    if (r.status === 304 && sameRef && prev.main) {
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
    st.stale = same ? prev.stale : null;
    return st;
  }
  if (st.main === st.sha) {
    st.stale = new Set();
    return st;
  }
  if (same && prev.main === st.main) {  // (same implies the same branch)
    st.stale = prev.stale;
    return st;
  }
  try {
    const r = await gh(env, `/compare/${st.sha}...${st.main}?per_page=1`, { headers: { accept: "application/vnd.github+json" } });
    // a daily push makes this response several MB of patches; parsing it can exceed the Free plan's 10 ms CPU. Above
    // COMPARE_MAX_BYTES it is treated like "300 or more files": stale stays null and files come from GitHub until appsync
    // records the new commit (cost report 26 Nov 2026)
    const len = Number(r.headers.get("content-length"));
    let raw = null;
    if (r.ok && !(len > COMPARE_MAX_BYTES)) {
      const buf = await r.arrayBuffer();
      if (buf.byteLength <= COMPARE_MAX_BYTES) raw = buf;
    } else if (r.body) {
      r.body.cancel().catch(() => {});
    }
    if (r.ok && raw) {
      const j = JSON.parse(new TextDecoder().decode(raw));
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
  if (!freshPending || Date.now() - freshPendingAt > PENDING_MAX_MS) {
    freshPendingAt = Date.now();
    const mine = checkFresh(env)
      .then((s) => (fresh = s))
      .catch((err) => {  // R2 itself failed: keep the last state (or trust nothing) and try again in a minute
        console.error(`r2 manifest: ${String(err).slice(0, 200)}`);
        fresh = fresh ? { ...fresh, at: Date.now() } : { at: Date.now(), sha: null, failed: new Set(), stale: null };
        return fresh;
      })
      .finally(() => {
        if (freshPending === mine) freshPending = null;
      });
    freshPending = mine;
  }
  if (age < FRESH_MAX_MS) {
    ctx.waitUntil(freshPending.catch(() => {}));
    return fresh;
  }
  // the check may belong to a cancelled request: wait a bounded time, then trust nothing (GitHub) for this request
  // (an older state could vouch for R2 files changed since; its sha and failed list still allow the R2 fallback in loadData)
  return within(freshPending, PENDING_WAIT_MS)
    .catch(() => ({ at: 0, sha: fresh ? fresh.sha : null, ref: fresh ? fresh.ref : undefined, failed: fresh ? fresh.failed : new Set(),
      stale: null }));
}

function r2Serves(st, path) {
  return !!(st && st.sha && st.stale && path.startsWith("data/") && !MAIN_PATHS.has(path) && !st.stale.has(path) &&
    !st.failed.has(path));
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
        const e = { body, etag: await contentEtag(body), r2etag: obj.etag, at: Date.now(), src: "r2" };
        dataMemSet(enc, e);
        return e;
      }
    } catch (err) {
      console.error(`r2 ${path}: ${String(err).slice(0, 200)}`);  // R2 failed: GitHub as before
    }
  }
  let got, err = null;
  try {
    got = await readData(env, enc, held && held.src !== "r2" ? held : null, refFor(env, st, path));
  } catch (e) {
    err = e;
  }
  // GitHub failed (5xx / network) while the freshness state could not vouch for R2: R2's copy beats nothing
  if ((err || (got && got.status >= 500)) && st && st.sha && path.startsWith("data/") && !st.failed.has(path)) {
    try {
      const obj = await env.DATA_R2.get(R2_PREFIX + path);
      if (obj !== null && typeof obj.arrayBuffer === "function") {
        const body = new Uint8Array(await obj.arrayBuffer());
        const e = { body, etag: await contentEtag(body), r2etag: obj.etag, at: Date.now(), src: "r2" };
        dataMemSet(enc, e);
        return e;
      }
    } catch (e2) {
      console.error(`r2 fallback ${path}: ${String(e2).slice(0, 200)}`);
    }
  }
  if (err) throw err;
  return got;
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

// Constant-time string compare for the app key (no early exit on the first differing character).
function sameKey(a, b) {
  const x = new TextEncoder().encode(String(a ?? "")), y = new TextEncoder().encode(String(b ?? ""));
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return d === 0;
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
    // 03:00 / 10:00 UTC = 08:30 / 15:30 IST -> IPO check; 11:40 UTC = 17:10 IST -> daily run; see CRON_JOBS
    const wf = CRON_JOBS.get(normCron(event.cron));
    if (!wf) {
      console.error(`cron ${JSON.stringify(event.cron)}: not a known schedule, nothing dispatched (update CRON_JOBS with wrangler.toml)`);
      return;
    }
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
    if (!env.APP_KEY || !sameKey(req.headers.get("x-app-key"), env.APP_KEY)) return bad(401, "app key");

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

    // Delayed quotes for the app (owner's choice A, 20 Nov 2026): up to 40 symbols, from Yahoo's public chart endpoint
    // (unofficial, may be delayed). Only symbols are sent; nothing about the owner. A bare symbol is NSE (.NS); a symbol sent
    // with .BO / .NS keeps it (BSE-only holdings). Held 60 s in isolate memory: the per-symbol Cache API match + put cost two
    // extra subrequests a symbol and do nothing on workers.dev, so 40 symbols needed 120 of the Free plan's 50 (audit 26 Nov
    // 2026); now one Yahoo call a symbol, at most 40.
    if (req.method === "GET" && url.pathname === "/quotes") {
      const syms = (url.searchParams.get("s") || "").split(",").map((x) => x.trim().toUpperCase())
        .filter((x) => /^[A-Z0-9&\-]{1,20}(\.(NS|BO))?$/.test(x)).slice(0, 40);
      if (!syms.length) return bad(400, "symbols");
      const out = {};
      await Promise.all(syms.map(async (s) => {
        const ys = /\.(NS|BO)$/.test(s) ? s : `${s}.NS`;
        const m0 = quoteMem.get(ys);
        if (m0 && Date.now() - m0.at < QUOTE_TTL_MS) {
          out[s] = m0.v;
          return;
        }
        const v = await yahooQuote(ys).catch(() => null);
        if (!v) return;
        quoteMem.set(ys, { v, at: Date.now() });
        if (quoteMem.size > 2000) quoteMem.delete(quoteMem.keys().next().value);
        out[s] = v;
      }));
      return new Response(JSON.stringify({ ok: true, src: "Yahoo chart (delayed)", quotes: out }), { headers: JSON_HDR });
    }

    // Home strip (feedback #145): Nifty 50 and Sensex (Yahoo chart, delayed), Gift Nifty near-month future (NSE IX website
    // data, unofficial) and gold 22K per 10 g (Abharan's daily rate, unofficial). Each source is cached on its own; one that
    // fails is left out and the app keeps its last value.
    if (req.method === "GET" && url.pathname === "/ticker") {
      const items = (await Promise.all([
        tickYahoo(ctx, "nifty", "NIFTY 50", "^NSEI"),
        tickYahoo(ctx, "sensex", "SENSEX", "^BSESN"),
        tickGift(ctx),
        tickGold(env, ctx),
      ])).filter(Boolean);
      return new Response(JSON.stringify({ ok: true, items }), { headers: { ...JSON_HDR, "cache-control": "no-store" } });
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
          e = { body, etag: hit.headers.get("etag") || (await contentEtag(body)), at: Date.now() };
        } else {
          const nf = notFound.get(enc);
          if (nf && Date.now() - nf < NOT_FOUND_TTL_MS) return bad(404, "github 404");
          let pe = dataPending.get(enc);
          if (!pe || Date.now() - pe.at > PENDING_MAX_MS) {
            const entry = { at: Date.now(), p: null };
            entry.p = loadData(env, ctx, enc, path, held).finally(() => {
              if (dataPending.get(enc) === entry) dataPending.delete(enc);
            });
            dataPending.set(enc, entry);
            pe = entry;
          }
          let got;
          try {
            got = await within(pe.p, PENDING_WAIT_MS);
          } catch {
            got = held || { status: 502 };  // GitHub unreachable or the shared read never settled: the last copy held, if any
          }
          if (got.status === 404) {
            notFound.set(enc, Date.now());
            if (notFound.size > 2000) notFound.delete(notFound.keys().next().value);
          }
          if (got.status) return bad(got.status === 404 ? 404 : 502, `github ${got.status}`);
          notFound.delete(enc);
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
      const meta = `\n\n---\nApp ${safe(clean(b.version, 20))} · screen \`${safe(clean(b.screen, 60).replace(/`/g, "'"))}\` · data ${safe(clean(b.dataDate, 20))}`;
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

// ---------------------------------------------------------------- Home strip (/ticker)
// In isolate memory first (the Cache API is a no-op on workers.dev, so every /ticker call made 4 fetches and an R2 read),
// then the edge cache (custom domain), then the source. Same TTLs as before: 30 s for prices, 1,800 s for gold.
const tickMem = new Map();     // key -> { v, at }
async function cached(ctx, key, ttl, make) {
  const m = tickMem.get(key);
  if (m && Date.now() - m.at < ttl * 1000) return m.v;
  const cache = caches.default;
  const k = new Request(`https://cache.narrativ/t/${key}`);
  const hit = await cache.match(k);
  if (hit) {
    const v = await hit.json();
    tickMem.set(key, { v, at: Date.now() });
    return v;
  }
  const v = await make().catch(() => null);
  if (v) {
    tickMem.set(key, { v, at: Date.now() });
    ctx.waitUntil(cache.put(k, new Response(JSON.stringify(v), { headers: { ...JSON_HDR, "cache-control": `public, max-age=${ttl}` } })));
  }
  return v;
}

// Previous close for a Yahoo chart: the last daily close dated before the latest price's day (IST) from a 5-day series, else
// Yahoo's own previous-close fields. chartPreviousClose is the close before the chart's range: after a holiday it was two
// sessions back (audit 26 Nov 2026: Nifty showed +2.11% for a +0.25% day), so it is the last resort only.
function prevClose(res) {
  const m = res.meta || {};
  const ist = (t) => new Date((t + 5.5 * 3600) * 1000).toISOString().slice(0, 10);
  const ts = Array.isArray(res.timestamp) ? res.timestamp : [];
  const cl = (((res.indicators || {}).quote || [])[0] || {}).close || [];
  if (m.regularMarketTime != null && ts.length) {
    const today = ist(m.regularMarketTime);
    for (let i = ts.length - 1; i >= 0; i--) {
      if (ist(ts[i]) < today && cl[i] != null && isFinite(cl[i]) && cl[i] > 0) return cl[i];
    }
  }
  for (const k of ["regularMarketPreviousClose", "previousClose", "chartPreviousClose"]) {
    if (m[k] != null && isFinite(m[k]) && m[k] > 0) return m[k];
  }
  return null;
}

// { p, prev, t } for one Yahoo symbol, or null.
async function yahooQuote(sym) {
  const y = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1d&range=5d`,
    { headers: { "user-agent": "Mozilla/5.0" } });
  if (!y.ok) return null;
  const res = (((await y.json().catch(() => ({}))).chart || {}).result || [])[0];
  const m = res && res.meta;
  if (!m || m.regularMarketPrice == null || !(m.regularMarketPrice > 0)) return null;
  return { p: m.regularMarketPrice, prev: prevClose(res), t: m.regularMarketTime ?? null };
}

function tickYahoo(ctx, k, name, sym) {
  return cached(ctx, k, 30, async () => {
    const q = await yahooQuote(sym);
    return q ? { k, name, ...q } : null;
  });
}

// "29-Dec-2026" -> epoch ms (UTC), or NaN.
function nseDate(s) {
  const m = /^(\d{1,2})[-\s]([A-Za-z]{3})[-\s](\d{4})/.exec(String(s || "").trim());
  const mon = m && "JANFEBMARAPRMAYJUNJULAUGSEPOCTNOVDEC".indexOf(m[2].toUpperCase());
  return m && mon >= 0 && mon % 3 === 0 ? Date.UTC(+m[3], mon / 3, +m[1]) : NaN;
}

const num = (x) => parseFloat(String(x ?? "").replace(/,/g, ""));

// The Gift Nifty row to show: the nearest expiry not yet past that has traded today; else the most traded; else the nearest.
// The feed lists far months too (audit 26 Nov 2026: row 0 was Jan 2027, 2 contracts, last trade hours old, change 0).
function giftRow(rows, now = Date.now()) {
  const today = Date.UTC(new Date(now).getUTCFullYear(), new Date(now).getUTCMonth(), new Date(now).getUTCDate());
  const fut = rows.filter((x) => x && x.SYMBOL === "NIFTY" && x.INSTRUMENTTYPE === "FUTIDX" && num(x.LASTPRICE) > 0)
    .map((x) => ({ x, exp: nseDate(x.EXPIRYDATE), n: num(x.CONTRACTSTRADED) || 0 }));
  if (!fut.length) return null;
  const live = fut.filter((f) => !(f.exp < today));
  const traded = live.filter((f) => f.n > 0).sort((a, b) => (a.exp || Infinity) - (b.exp || Infinity));
  if (traded.length) return traded[0].x;
  return (live.length ? live : fut).sort((a, b) => b.n - a.n || (a.exp || Infinity) - (b.exp || Infinity))[0].x;
}

function tickGift(ctx) {
  return cached(ctx, "gift", 30, async () => {
    const r = await fetch("https://www.nseix.com/api/market-rate?type=derivatives",
      { headers: { "user-agent": "Mozilla/5.0", referer: "https://www.nseix.com/" } });
    if (!r.ok) return null;
    const data = (await r.json()).data;
    const row = giftRow(Array.isArray(data) ? data : []);
    const p = row ? num(row.LASTPRICE) : NaN;
    if (!isFinite(p) || p <= 0) return null;
    const ch = num(row.DAYCHANGE_1 ?? row.DAYCHANGE);
    return { k: "gift", name: "GIFT NIFTY", p, prev: isFinite(ch) && p - ch > 0 ? p - ch : null, at: row.TIMESTMP || null,
             exp: row.EXPIRYDATE || null };
  });
}

// Abharan publishes one rate a day (per gram); the previous different rate is kept in R2 so the app can show the change.
function tickGold(env, ctx) {
  return cached(ctx, "gold22", 1800, async () => {
    const r = await fetch("https://services.abharan.com/api/v1/website/dailyrate", { headers: { "user-agent": "Mozilla/5.0" } });
    if (!r.ok) return null;
    const g = parseFloat(((await r.json()).data || {}).gold22);
    if (!isFinite(g) || g <= 0) return null;
    const p = g * 10;
    const today = new Date(Date.now() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);
    let prev = null, date = today;
    if (env.DATA_R2) {
      // a failed or unreadable history read must not overwrite the stored history (audit 26 Nov 2026)
      const key = "ticker/gold22.json";
      let o, ok = true;
      try {
        o = await env.DATA_R2.get(key);
      } catch {
        ok = false;
      }
      let h = null; // { p, date, prev, prevDate }
      if (ok && o) {
        h = await o.json().catch(() => undefined);
        if (h === undefined || !h || typeof h !== "object") ok = false;
      }
      if (ok && h && h.p === p) {
        prev = h.prev ?? null;
        date = h.date || today;  // the day this rate was first seen (the API carries no date)
      } else if (ok) {
        prev = h ? h.p : null;
        ctx.waitUntil(env.DATA_R2.put(key, JSON.stringify({ p, date: today, prev, prevDate: h ? h.date : null })).catch(() => null));
      }
    }
    return { k: "gold22", name: "GOLD 22K · 10G", p, prev, date };
  });
}
