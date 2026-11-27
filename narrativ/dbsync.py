"""Daily run -> D1 tables + R2 files. Called at the end of run.py; never fatal. Design and volumes: db/README.md."""
import gzip
import hashlib
import json
import os
import pickle
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import events as EV
from .store import Store
from .util import digest, file_digest, write_if_changed

CR = 1e7
MANIFEST = Path("data/d1_manifest.json")  # content hash of every row / object already written; committed with the daily data
REFRESH_DAYS = int(os.environ.get("D1_REFRESH_DAYS", "7"))  # a table or object older than this is rewritten in full (self-heals drift)

# Big or append-only tables: the drift guard looks up a few rows the manifest says were written (primary-key lookups)
# instead of COUNT(*), which D1 bills as one row read per row in the table (snapshot alone grows ~2,400 rows a day).
PROBE = {"snapshot": ("isin", "date"), "event": ("id",), "quarter": ("isin", "period_end", "basis"),
         "industry_breadth": ("date", "level", "grp")}

# Stores that live in the GitHub Actions cache (evicted after 7 days unused, or earlier by the 10 GB repo cap) and their
# durable copy in R2. (local file, R2 key, "raw" = already gzip, uploaded as is | "gz" = gzipped on upload, unzipped on
# restore). Uploaded only when the content hash changed (manifest); restored by restore_caches() when the local file is missing.
DURABLE = (
    ("data/source_cache/announcements.json.gz", "announcements/store.json.gz", "raw"),
    ("data/source_cache/bse_announcements.json.gz", "announcements/bse_store.json.gz", "raw"),
    ("data/source_cache/prices_meta.json", "prices/prices_meta.json.gz", "gz"),  # adjustments already applied: travels with prices
    ("data/source_cache/delivery.json", "nse/delivery.json.gz", "gz"),
    ("data/source_cache/indices.json", "nse/indices.json.gz", "gz"),
    ("data/source_cache/shp.json", "nse/shp.json.gz", "gz"),
    ("data/source_cache/corpfil.json", "nse/corpfil.json.gz", "gz"),
    ("data/source_cache/index_hist.json", "nse/index_hist.json.gz", "gz"),
    ("data/source_cache/bulk_deals.json", "nse/bulk_deals.json.gz", "gz"),
    ("data/source_cache/ratings_sdd.json.gz", "nse/ratings_sdd.json.gz", "raw"),
    ("data/source_cache/ibbi.json.gz", "ibbi/ibbi.json.gz", "raw"),
    ("data/source_cache/bse_list.json", "bse/bse_list.json.gz", "gz"),
    ("data/news_cache/news.json.gz", "news/news.json.gz", "raw"),
)
# Directories of small files that are kept for good (AlphaStreet FINAL transcripts and briefs do not change): one R2
# bundle each, {file name: text} as gzipped JSON, re-uploaded only when a file was added or changed.
DURABLE_DIRS = (
    ("data/source_cache/alphastreet/transcripts", "alphastreet/transcripts.json.gz"),
    ("data/source_cache/alphastreet/briefs", "alphastreet/briefs.json.gz"),
)
# Not copied (re-creatable or scratch): alphastreet/lists (valid for one day), bse_deliv (download folder, emptied after
# parsing into delivery.json), bhav/ (last 15 public exchange files), doctext/ and roid/ (text read from public PDFs),
# pinksheet.xlsx (World Bank file). surveillance.json is archived as one dated object a day, not restored.

SURVEILLANCE_DAYS = 90   # R2 nse/surveillance-<date>.json.gz kept this long
BACKUPS_KEEP = 12        # R2 backups/memory-<monday>.json.gz: the latest 12 weekly copies
PRUNE_EVERY_DAYS = 7     # R2 listing is a Class A operation: prune weekly, not every run
_DATED = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _cr(x):
    return None if x is None else round(x / CR, 2)


DAILY_CAP = 95_000   # D1 Free allows 100,000 rows written per UTC day; every run the same UTC day shares this
IN_LIST = 90         # values bound per statement (D1 allows 100 bound parameters)
BACKFILL_SHARE = 0.5  # history backfills (industry breadth, older events) may use at most this share of what is left
EVENT_CATCHUP_DAYS = 30  # events of days not yet synced (budget-cut or failed runs) are re-sent up to this far back


def _utc_day() -> str:
    """The UTC day of this run: D1's daily write limit resets at 00:00 UTC, whatever date the data carries."""
    return datetime.now(timezone.utc).date().isoformat()


def _mark_gone(st, man, table: str, keys: list, sql: str, h_old: dict) -> int:
    """Flag rows that left the source (UPDATE/DELETE ... WHERE key IN (...)), IN_LIST keys a statement. Keys whose statement
    failed go back into the manifest, so the next run finds them gone again and retries (audit 26 Nov 2026)."""
    failed, done = [], 0
    for k in range(0, len(keys), IN_LIST):
        ch = keys[k:k + IN_LIST]
        try:
            st.q(sql.format(",".join("?" * len(ch))), ch)
            done += len(ch)
        except Exception as e:  # noqa: BLE001
            print(f"[store] {table}: flagging {len(ch)} removed rows failed: {e}")
            failed += ch
    if failed:
        t = man.data["tables"].setdefault(table, {"at": str(man.today), "h": {}})
        t.setdefault("h", {}).update({k: h_old[k] for k in failed if k in h_old})
        man.dirty = True
    return done


def _json(p: Path) -> dict:
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


class Manifest:
    """What the last successful syncs wrote, as content hashes: {"schema": h, "tables": {t: {"at": date, "h": {key: hash},
    "p": [probe keys]}}, "r2": {key: [hash, date]}, "done": {housekeeping task: date}}.

    A missing, unreadable or distrusted manifest means "send everything" (the original behaviour). Entries are recorded only for
    rows D1 accepted, so a failed or budget-cut write is retried on the next run."""

    def __init__(self, path: Path, today: date):
        self.path, self.today = path, today
        self.data = {"v": 1, "schema": None, "tables": {}, "r2": {}}
        try:
            d = json.loads(path.read_text())
            if isinstance(d, dict) and d.get("v") == 1:
                self.data = {**self.data, **d}
        except Exception:  # noqa: BLE001
            pass
        self.dirty = False

    def _age(self, at) -> int:
        try:
            return (self.today - date.fromisoformat(at)).days
        except Exception:  # noqa: BLE001
            return 10 ** 6

    def rows(self, table: str) -> dict:
        t = (self.data["tables"].get(table) or {})
        return dict(t.get("h") or {}) if t.get("h") and self._age(t.get("at")) < REFRESH_DAYS else {}

    def set_rows(self, table: str, h: dict, full: bool, probe: list | None = None) -> None:
        prev = self.data["tables"].get(table) or {}
        t = {"at": str(self.today) if full else prev.get("at") or str(self.today), "h": h}
        if probe or prev.get("p"):
            t["p"] = probe or prev["p"]
        self.data["tables"][table] = t
        self.dirty = True

    def due(self, task: str, every_days: int) -> bool:
        """Housekeeping (retention) that runs at most once per `every_days`."""
        return self._age((self.data.get("done") or {}).get(task)) >= every_days

    def did(self, task: str) -> None:
        self.data.setdefault("done", {})[task] = str(self.today)
        self.dirty = True

    def drop(self, table: str | None = None) -> None:
        """Distrust one table (or everything) after a drift check failed."""
        if table is None:
            self.data = {"v": 1, "schema": None, "tables": {}, "r2": {}}
        else:
            self.data["tables"].pop(table, None)
        self.dirty = True

    def r2_fresh(self, key: str, h: str) -> bool:
        e = self.data["r2"].get(key)
        return bool(e) and e[0] == h and self._age(e[1]) < REFRESH_DAYS

    def r2_done(self, key: str, h: str) -> None:
        self.data["r2"][key] = [h, str(self.today)]
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            write_if_changed(self.path, json.dumps(self.data, sort_keys=True, separators=(",", ":")))


def upsert_changed(st: Store, man: Manifest, table: str, cols: list[str], rows: list[list], keys: list[str], keep: tuple = (),
                   ignore: tuple = (), hash_of=None, short: bool = False) -> tuple[int, int]:
    """Upsert only the rows whose content hash differs from the manifest (all rows when the manifest has nothing for the table).

    `ignore` columns are left out of the hash (volatile values that alone are not worth a write; they ride along when the row
    is written for another reason). `hash_of(row)` replaces the column-based hash when a single field of a JSON column is volatile.
    `short` stores a 12-character hash of the key in the manifest instead of the key itself (long keys such as URLs).
    The manifest holds only the keys of `rows`: for an append-only table pass today's rows (reruns then skip what is unchanged).
    Returns (rows sent, rows unchanged and skipped)."""
    kidx = [cols.index(k) for k in keys]
    hidx = [i for i, c in enumerate(cols) if c not in ignore]
    pidx = [cols.index(c) for c in PROBE.get(table, ())]
    old = man.rows(table)
    new, todo = {}, []
    for r in rows:
        k = "|".join(str(r[i]) for i in kidx)
        if short:
            k = digest(k, 12)
        h = digest(hash_of(r) if hash_of else [r[i] for i in hidx])
        new[k] = h
        if old.get(k) != h:
            todo.append((k, r))
    ok = set()
    err = None
    try:
        st.upsert(table, cols, [r for _, r in todo], keys, keep=keep, on_sent=lambda idx: ok.update(todo[i][0] for i in idx))
    except Exception as e:  # noqa: BLE001
        err = e
    # unchanged rows and rows D1 accepted record the new hash; rows that were not sent keep their old one (or none) so they retry
    final = {k: h for k, h in new.items() if k in ok or old.get(k) == h}
    final.update({k: old[k] for k in new if k not in final and k in old})
    probe = sorted(([r[i] for i in pidx] for k, r in todo if k in ok), key=str)[:3] if pidx else None  # rows known to be in D1 now
    man.set_rows(table, final, full=not old and len(ok) == len(todo), probe=probe)
    if err:
        raise err
    return len(ok), len(rows) - len(todo)


# forward_item columns added by the forward ledger, stage 1 (narrativ/ledger.py, 27 Nov 2026)
FWD_NEW = (("ftype", "TEXT"), ("measure", "TEXT"), ("period", "TEXT"), ("amount", "REAL"), ("base", "REAL"), ("size_pct", "REAL"),
           ("trend_pct", "REAL"), ("material", "INTEGER"), ("size_why", "TEXT"), ("prev_id", "TEXT"), ("change", "TEXT"),
           # stage 2 (narrativ/monitor.py): progress at the last filing, its projection, and the outcome once the year is filed
           ("progress", "TEXT"), ("projected", "REAL"), ("outcome", "TEXT"))
SNAP_NEW = (("decision", "TEXT"), ("candidate", "TEXT"), ("verified", "TEXT"), ("rk", "INTEGER"), ("mb", "INTEGER"), ("conviction", "TEXT"))


def sync(today: date, s0i, btypes: dict, lender: dict, picks: list, details: dict, fins: dict, mem: dict, theses: dict,
         md: dict, ann_st: dict, extra_counts: dict | None = None, breadth_in: tuple | None = None) -> dict:
    """breadth_in: (prices, isin by symbol, market cap cr by symbol, momentum score by symbol) for the industry_breadth table."""
    t0 = time.time()
    st = Store()
    if not st.db:
        return {"ok": False}
    d = str(today)
    stages, counts = {}, {}
    man = Manifest(MANIFEST, today)
    try:
        # drift guard: the manifest is trusted only while D1 still holds at least the rows it says were written
        def is_gone(tb) -> bool:
            t = man.data["tables"][tb]
            if tb in PROBE:  # big table: the sample rows the manifest recorded must still be there
                p = t.get("p") or []
                return bool(t.get("h")) and (not p or st.probe(tb, PROBE[tb], p) < len(p))
            return st.count(tb) < len(t.get("h") or {})

        for tb in list(man.data["tables"]):
            err = None
            for _ in range(2):  # one retry: a transient D1 error must not throw away the whole manifest (audit 26 Nov 2026)
                try:
                    if is_gone(tb):
                        print(f"[store] {tb}: D1 holds fewer rows than the manifest; full resend")
                        man.drop(tb)
                    err = None
                    break
                except Exception as e:  # noqa: BLE001
                    err = e
            if err is None:
                continue
            if "no such table" in str(err).lower():  # the database was recreated: nothing the manifest says is there
                print(f"[store] manifest distrusted ({tb}: {err}); full sync")
                man.drop()
            else:
                print(f"[store] drift check skipped this run ({tb}: {err})")
            break
        fp = Store.schema_fingerprint(repr((SNAP_NEW, FWD_NEW)))
        if man.data.get("schema") == fp:
            print("[store] schema unchanged since the last sync; skipping apply_schema")
        else:
            st.apply_schema()
            try:  # daily decision history (for backtesting the rules): columns added after the table was created
                have = {r.get("name") for r in st.q("PRAGMA table_info(snapshot)")}
                for c, t in SNAP_NEW:
                    if have and c not in have:
                        st.q(f"ALTER TABLE snapshot ADD COLUMN {c} {t}")
                have = {r.get("name") for r in st.q("PRAGMA table_info(forward_item)")}
                for c, t in FWD_NEW:
                    if have and c not in have:
                        st.q(f"ALTER TABLE forward_item ADD COLUMN {c} {t}")
                man.data["schema"] = fp
                man.dirty = True
            except Exception as e:  # noqa: BLE001
                print(f"[store] snapshot columns: {e}")
        utc = _utc_day()
        try:  # every run the same UTC day shares the 100k/day D1 limit, whatever data date each carries (audit 26 Nov 2026)
            prev = st.q("SELECT usage, date FROM run_log WHERE date >= ?", [str(today - timedelta(days=4))])
            done = 0
            for row in prev:
                try:
                    u0 = json.loads(row.get("usage") or "{}")
                except (TypeError, ValueError):
                    continue
                same = u0.get("utc_day") == utc if u0.get("utc_day") else row.get("date") == d  # rows before utc_day: by data date
                if same:
                    done = max(done, int(u0.get("d1_rows_written_today", u0.get("d1_rows_written", 0)) or 0))
            st.prior = done
            if done:
                st.budget = max(0, min(st.budget, DAILY_CAP - done))
                print(f"[store] {done} rows already written this UTC day; budget {st.budget}")
        except Exception as e:  # noqa: BLE001
            print(f"[store] could not read today's usage: {e}")
        isin = {s: (s0i.loc[s, "isin"] if "isin" in s0i.columns else None) for s in s0i.index}
        isin = {s: i for s, i in isin.items() if isinstance(i, str) and i}

        def step(name, fn):
            t = time.time()
            try:
                counts[name] = fn()
            except Exception as e:  # noqa: BLE001
                counts[name] = f"failed: {str(e)[:200]}"
                print(f"[store] {name} failed: {e}")
            stages[name] = round(time.time() - t, 1)

        def company():
            rows = []
            for s, i in isin.items():
                b = s0i.loc[s]
                nm = b["longName"] if isinstance(b["longName"], str) else b.get("shortName")
                rows.append([i, s, "NSE" if s.endswith(".NS") else "BSE", b.get("bse_code"), nm,
                             b["sector"] if isinstance(b["sector"], str) else None, b["industry"] if isinstance(b["industry"], str) else None,
                             (btypes.get(s) or (None,))[0], 1 if lender.get(s) else 0,
                             round(float(b["marketCap"]) / CR, 1) if b["marketCap"] == b["marketCap"] and b["marketCap"] is not None else None,
                             1, d, d])
            trusted = man.rows("company")  # isins written by earlier syncs (empty = full sync)
            n, skipped = upsert_changed(st, man, "company", ["isin", "symbol", "exchange", "bse_code", "name", "sector", "industry", "business_type",
                                                             "is_lender", "mcap_cr", "in_universe", "first_seen", "last_seen"], rows, ["isin"],
                                        keep=("first_seen",), ignore=("first_seen", "last_seen"))
            if trusted:
                # unchanged rows were not rewritten, so their last_seen is older than today: flag departures by name instead
                # (IN_LIST a statement; a failed statement puts its ISINs back in the manifest so the next run retries)
                gone = sorted(set(trusted) - set(isin.values()))
                _mark_gone(st, man, "company", gone, "UPDATE company SET in_universe = 0 WHERE isin IN ({})", trusted)
            elif n == len(rows):  # full set written today: every row not seen today has left
                st.q("UPDATE company SET in_universe = 0 WHERE last_seen < ?", [d])
            else:  # a budget cut left rows with an old last_seen that are still in the universe (audit 26 Nov 2026)
                print(f"[store] company: {n} of {len(rows)} rows sent; departures flagged once the full set is written")
            return n

        def quarter():
            # new filings every day; companies with nothing stored yet are backfilled inside the remaining budget
            have = {r["isin"] for r in st.q("SELECT DISTINCT isin FROM quarter")}
            # re-read since the last quarter sync that sent everything (a budget-cut or failed run is not "synced": audit
            # 26 Nov 2026, filings were lost after two starved runs); before the marker existed: the previous run_log date
            since = (man.data.get("done") or {}).get("quarter_synced")
            if not since:
                prev = st.q("SELECT MAX(date) AS m FROM run_log WHERE date < ?", [d])
                since = (prev[0]["m"] if prev and prev[0]["m"] else d)
            rows = []
            for s, rec in fins.items():
                i = isin.get(s)
                if not i or not rec or (i in have and str(rec.get("checked", ""))[:10] < since):
                    continue
                for qe, bases in (rec.get("quarters") or {}).items():
                    for basis, p in bases.items():
                        q, bs = p.get("q") or {}, p.get("bs") or {}
                        eb = q["rev"] - q["exp"] + (q.get("fin") or 0) + (q.get("dep") or 0) if q.get("rev") is not None and q.get("exp") is not None else None
                        rows.append([i, qe, basis, p.get("kind"), _cr(q.get("rev")), _cr(eb), _cr(q.get("pat")), _cr(q.get("pat_owners")), q.get("eps"),
                                     _cr(bs.get("equity")), _cr((bs.get("borr_cur") or 0) + (bs.get("borr_ncur") or 0)) if bs.get("borr_cur") is not None or bs.get("borr_ncur") is not None else None,
                                     _cr(bs.get("cash")), {"q": q, "ytd": p.get("ytd"), "bs": bs, "flags": p.get("flags"), "shares": p.get("shares")},
                                     p.get("filed"), 1 if p.get("audited") else 0, p.get("url")])
            # BSE results summary (companies with no NSE results filings): revenue, profit, EPS per quarter
            try:
                from pathlib import Path as _P
                br = json.loads(_P("data/bse_results.json").read_text()) if _P("data/bse_results.json").exists() else {}
            except Exception:  # noqa: BLE001
                br = {}
            for s, rec in br.items():
                i = isin.get(s)
                if not i or (i in have and str(rec.get("checked", ""))[:10] < since):
                    continue
                for qe, x in (rec.get("q") or {}).items():
                    rows.append([i, qe, "BSE summary", "bse", x.get("rev"), None, x.get("pat"), x.get("pat"), x.get("eps"), None, None, None,
                                 {"src": "BSE results summary", "fy": rec.get("fy")}, rec.get("checked"), 0, rec.get("url")])
            # a rerun the same day re-reads the same filings: only rows whose content changed are sent again
            n, same = upsert_changed(st, man, "quarter", ["isin", "period_end", "basis", "kind", "revenue_cr", "ebitda_cr", "pat_cr", "pat_owners_cr",
                                                          "eps", "equity_cr", "borrowings_cr", "cash_cr", "extra", "filed_on", "audited", "source_url"],
                                     rows, ["isin", "period_end", "basis"], short=True)
            if n + same == len(rows):
                man.data.setdefault("done", {})["quarter_synced"] = d
                man.dirty = True
            return n

        def snapshot():
            """One row per stock per trading date (history). A rerun the same day sends only the stocks whose row changed
            (24 Nov 2026: 12 reruns re-sent all 2,360 rows each time); the manifest holds today's keys only."""
            rows = []
            for p in picks:
                i = isin.get(p["s"])
                if not i:
                    continue
                t, sc = (p.get("t") or [None] * 7), (p.get("sc") or [None] * 7)
                rows.append([i, d, p.get("p"), p.get("mc"), p.get("d1"), *t[:7], *sc[:7], p.get("vd"), p.get("pr"), p.get("su") or p.get("ss"),
                             (p.get("out") or {}).get("l"), (p.get("out") or {}).get("w"),
                             p.get("dc"), p.get("cand"), p.get("vf"), p.get("rk"), 1 if p.get("mb") else 0, p.get("cv")])
            n = upsert_changed(st, man, "snapshot", ["isin", "date", "price", "mcap_cr", "chg_1d", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
                                                     "s1", "s2", "s3", "s4", "s5", "s6", "s7", "verdict", "priority", "setup", "removed_level",
                                                     "removed_reason", *[c for c, _ in SNAP_NEW]],
                               rows, ["isin", "date"], short=True)[0]
            # retention (decision 1-b): daily for 365 days, then Mondays only. Once a day: without a date index the DELETE
            # reads the whole table (~0.9M rows after a year, inside the 5M rows read a day of D1 Free).
            if man.due("snapshot_retention", 1):
                st.q("DELETE FROM snapshot WHERE date < ? AND strftime('%w', date) != '1'", [str(today - timedelta(days=365))])
                man.did("snapshot_retention")
            return n

        def detail():
            # the readiness rank (rk) reshuffles for ~every stock daily and is in the snapshot table; it alone no longer
            # rewrites a ~16 KB row. `date` is the day the row was last written (a full refresh runs every REFRESH_DAYS).
            rows = [[isin[p["s"]], d, p, details.get(p["s"])] for p in picks if p["s"] in isin]
            return upsert_changed(st, man, "stock_detail", ["isin", "date", "pick", "detail"], rows, ["isin"], ignore=("date",),
                                  hash_of=lambda r: [r[0], {k: v for k, v in r[2].items() if k != "rk"}, r[3]])[0]

        ev = {"old": [], "cost": 3.0, "oldest": "9999"}

        def event():
            # daily: every day since the last sync that sent its whole window (at least the last 3 days, at most
            # EVENT_CATCHUP_DAYS), only rows that are new or changed (manifest). A budget-cut or failed run leaves the marker,
            # so its days are sent by a later run (audit 26 Nov 2026: days between the backfill edge and the last 3 days were
            # never sent). Older history is backfilled by event_backfill() after the daily essentials.
            # D1 counts each index update as a written row, so one event costs ~3 rows (table, primary key, event_isin_date).
            backfill = not st.prior
            r = st.q("SELECT MIN(date) AS m FROM event WHERE exchange = 'NSE'") if backfill else []  # reads the whole table
            oldest = ev["oldest"] = (r[0]["m"] if r and r[0]["m"] else "9999")
            recent = str(today - timedelta(days=3))
            start = recent
            synced = (man.data.get("done") or {}).get("event_synced")
            if synced:
                try:
                    start = min(recent, str(date.fromisoformat(synced) - timedelta(days=3)))
                except ValueError:
                    pass
            start = max(start, str(today - timedelta(days=EVENT_CATCHUP_DAYS)))
            rows, seen = [], set()
            for s, rs in (ann_st.get("rows") or {}).items():
                i = isin.get(s)
                if not i:
                    continue
                for dt, cat, txt, url, g, rule in rs:
                    if dt < start and dt > oldest:  # the oldest stored day is re-sent: heals a day cut short by the budget
                        continue
                    k = url or f"NSE|{i}|{dt}|{(txt or '')[:80]}"
                    if k in seen:
                        continue
                    seen.add(k)
                    typ, sev = EV.classify(f"{txt or ''} {cat or ''}")
                    rows.append([k, i, s, dt, "NSE", cat, txt, g, rule, sev, typ, url, d])
            for s, rec in mem.items():  # BSE-only listings: events gathered per stock
                i = isin.get(s)
                if not i or s.endswith(".NS"):
                    continue
                for e in rec.get("events") or []:
                    if (e.get("date") or "") < start:
                        continue
                    k = e.get("url") or f"BSE|{i}|{e.get('date')}|{(e.get('text') or '')[:80]}"
                    if k not in seen:
                        seen.add(k)
                        rows.append([k, i, s, e.get("date"), "BSE", e.get("category"), e.get("text"), None, None, e.get("sev"), e.get("type"), e.get("url"), d])
            rows.sort(key=lambda r: r[3] or "", reverse=True)
            cols = ["id", "isin", "symbol", "date", "exchange", "category", "subject", "doc_group", "rule", "severity", "type", "url", "first_seen"]
            new = [r for r in rows if (r[3] or "") >= start]
            ev["old"] = [r for r in rows if (r[3] or "") < start] if backfill else []
            w0 = st.rows_written
            sent, same = upsert_changed(st, man, "event", cols, new, ["id"], keep=("first_seen",), ignore=("first_seen",), short=True)
            if sent:
                ev["cost"] = (st.rows_written - w0) / sent  # D1 rows written per event, indexes included
            if sent + same == len(new):
                man.data.setdefault("done", {})["event_synced"] = d
                man.dirty = True
            print(f"[store] events: {sent} since {start} ({same} unchanged; oldest stored {oldest}; {ev['cost']:.1f} D1 rows per event)")
            return sent

        def event_backfill():
            # older history, first sync of the UTC day only: whole days (newest first), each only if it fits, so MIN(date) is
            # always a clean boundary
            old = ev["old"]
            if not old:
                return 0
            stop = min(st.budget, DAILY_CAP - st.prior) - 2_000
            days: dict = {}
            for r in old:
                days.setdefault(r[3], []).append(r)
            back = 0
            cols = ["id", "isin", "symbol", "date", "exchange", "category", "subject", "doc_group", "rule", "severity", "type", "url", "first_seen"]
            for dt in sorted(days, reverse=True):
                if st.rows_written + len(days[dt]) * ev["cost"] * 1.2 > stop:
                    break
                back += st.upsert("event", cols, days[dt], ["id"], keep=("first_seen",))
            print(f"[store] events backfill: {back} of {len(old)} older (oldest stored {ev['oldest']})")
            return back

        def checkpoint():
            rows = []
            for s, rec in mem.items():
                i = isin.get(s)
                for c in (rec.get("checkpoints") or []) if i else []:
                    if not c.get("id"):
                        continue
                    rows.append([c["id"], i, c.get("type"), c.get("due"), c.get("what"), c.get("expected"), c.get("source"), c.get("status"),
                                 c.get("resolved_on") or c.get("resolved"), c.get("outcome")])
            return upsert_changed(st, man, "checkpoint", ["id", "isin", "type", "due", "what", "expected", "source", "status", "resolved_on", "outcome"],
                                  rows, ["isin", "id"])[0]

        def signals():
            """forward_signal: the ledger monitor's signals (narrativ/monitor.py), append-only; today's rows only."""
            p = Path("data/ledger_signals.json")
            if not p.exists():
                return 0
            rows = []
            for x in json.loads(p.read_text()).get("signals", []):
                i = isin.get(x.get("sym"))
                if i and x.get("date") == d:
                    rows.append([digest([x["date"], x["item"], x["kind"], x["status"]], 20), i, x["item"], x["date"], x["kind"],
                                 x["status"], x["dir"], x.get("material"), x.get("measure"), x.get("text"),
                                 json.dumps(x.get("detail"), separators=(",", ":"), ensure_ascii=False)])
            return upsert_changed(st, man, "forward_signal", ["id", "isin", "item_id", "date", "kind", "status", "dir", "material", "measure",
                                                              "text", "detail"], rows, ["id"])[0]

        def verdicts():
            """priority: the funnel priority (run.py ev[s]["pr"]) on the verdict's date, from the stock's memory snapshots
            (kept 400 days) or today's pick; NULL for an older change whose snapshot is gone."""
            # full resend: a new table, or once to fill priority on rows written before it was recorded (25 Nov 2026)
            once = man.due("verdict_priority_backfill", 10 ** 5)
            full = once or st.count("verdict_log") < 100
            # every change since the last run that sent all of its rows (audit 26 Nov 2026: only today's were sent, so a day
            # whose sync failed or was cut was never sent)
            since = (man.data.get("done") or {}).get("verdict_log_synced") or d
            pr_today = {p["s"]: p.get("pr") for p in picks}
            now, hist = [], []
            for s, rec in mem.items():
                i = isin.get(s)
                if not i:
                    continue
                pr = {x.get("d"): x.get("pr") for x in rec.get("snapshots") or [] if isinstance(x, dict)}
                if pr_today.get(s) is not None:
                    pr.setdefault(d, pr_today[s])
                for v in rec.get("verdicts") or []:
                    vd = v.get("d") or ""
                    if full or vd >= since:
                        # memory holds only today's tiers: they belong to today's row; an older row keeps the tiers it was
                        # written with (a resend wrote today's tiers onto every historic row)
                        (now if vd == d else hist).append([i, v.get("d"), v.get("from"), v.get("v"), pr.get(v.get("d")),
                                                           rec.get("tiers") if vd == d else None])
            cols = ["isin", "date", "verdict_from", "verdict_to", "priority", "tiers"]
            n = st.upsert("verdict_log", cols, now, ["isin", "date"])
            n += st.upsert("verdict_log", cols, hist, ["isin", "date"], keep=("tiers",))
            if n == len(now) + len(hist):
                man.data.setdefault("done", {})["verdict_log_synced"] = d
                man.dirty = True
                if once:
                    man.did("verdict_priority_backfill")
            return n

        def research():
            rows = [[isin[s], s, t.get("updated"), t.get("quarter"), t.get("source_type"), t.get("outlook_score"),
                     {k: v for k, v in t.items() if k != "scan_raw"}] for s, t in theses.items() if s in isin]
            old = man.rows("research")
            n = upsert_changed(st, man, "research", ["isin", "symbol", "updated", "quarter", "source_type", "outlook_score", "thesis"], rows, ["isin"])[0]
            # a thesis no longer held (company left, research withdrawn) leaves the table, which holds verified research only
            gone = sorted(set(old) - {r[0] for r in rows})
            if gone:
                _mark_gone(st, man, "research", gone, "DELETE FROM research WHERE isin IN ({})", old)
            return n

        def forward():
            """forward_item: every forward-looking statement we hold. Claude's drivers (status verified when the verifier
            confirmed the due date from the quote, else open) and promises (their tracked status), and the free readers'
            rows from every document read (status unconfirmed). first_seen is kept from the first write."""
            rows, led = [], []

            def add(sym, origin, key, kind, text, value, unit, due, direction, status, quote, url, doc_date, target=None):
                i = isin.get(sym)
                if i and text:
                    rid = digest([sym, origin.split(":")[0], key], 20)
                    rows.append([rid, i, kind, text, value if isinstance(value, (int, float)) else None,
                                 unit, due, direction, status, origin, quote, url, doc_date, d, d])
                    led.append({"id": rid, "sym": sym, "grp": "reader" if origin.startswith("reader") else "narrativ", "kind": kind,
                                "text": text, "value": value, "unit": unit, "due": due, "made": doc_date, "target": target})
            for s, t in theses.items():
                for x in t.get("drivers") or []:
                    add(s, "claude", [x.get("text"), x.get("due")], x.get("kind"), x.get("text"), x.get("value"), x.get("unit"), x.get("due"),
                        x.get("direction"), "verified" if x.get("due_verified") else "open", x.get("quote"), x.get("source"), x.get("date"),
                        x.get("target"))
                for x in t.get("promises") or []:
                    add(s, "promise", [x.get("id") or x.get("promise")], x.get("kind"), x.get("promise"), None, None, x.get("due"), None,
                        x.get("status") or "open", x.get("quote"), x.get("source"), x.get("made_on"), x.get("target"))
            rp = Path("data/reader/store.json")
            for url, e in (json.loads(rp.read_text()) if rp.exists() else {}).items():
                r = next((e[m] for m in ("flash", "lite") if "rows" in (e.get(m) or {})), None)
                for x in (r or {}).get("rows") or []:
                    add(e.get("s"), f"reader:{r.get('model')}", [url, x.get("text"), x.get("due")], x.get("kind"), x.get("text"), x.get("value"),
                        x.get("unit"), x.get("due"), x.get("direction"), "unconfirmed", x.get("quote") or x.get("text"), url, e.get("date"))
            # ledger stage 1: type, base, size, materiality and the earlier version of Narrativ.ai's verified items only (owner,
            # 27 Nov 2026: only verified quotes count); free-reader rows stay unsized until Narrativ.ai confirms them
            try:
                from . import ledger as LG
                bases = LG.Bases(fins)
                mine = [r for r in led if r["grp"] == "narrativ"]
                for r in mine:
                    r.update(LG.size_item(r["sym"], r["kind"], r["text"], r["value"], r["unit"], r["due"], r["made"], bases, r["target"]))
                    if r.get("src") == "parsed" and r.get("why") is None:
                        r["why"] = "parsed from the text: provisional until Narrativ.ai records the target"
                LG.link(mine)
                for r in led:
                    if r["grp"] == "reader":
                        r["why"] = "free-reader row: not sized until Narrativ.ai confirms it"
            except Exception as e:  # noqa: BLE001
                print(f"[store] ledger sizing skipped: {e}")
            lf = ("ftype", "measure", "period", "amount", "base", "size_pct", "trend_pct", "material", "why", "prev", "change")
            try:
                mon = json.loads(Path("data/ledger_state.json").read_text()).get("items", {})
            except Exception:  # noqa: BLE001
                mon = {}
            for row, r in zip(rows, led):
                pg = (mon.get(r["id"]) or {}).get("progress") or {} if r["grp"] == "narrativ" else {}
                row.extend([*(r.get(k) for k in lf), pg.get("status"), pg.get("projected", pg.get("actual")),
                            (mon.get(r["id"]) or {}).get("outcome") if r["grp"] == "narrativ" else None])
            seen, uniq = set(), []
            for r in rows:
                if r[0] not in seen:
                    seen.add(r[0])
                    uniq.append(r)
            cols = ["id", "isin", "kind", "metric", "value", "unit", "due", "direction", "status", "origin", "quote", "url", "doc_date",
                    "first_seen", "last_checked", *[c for c, _ in FWD_NEW]]
            old = man.rows("forward_item")
            n = upsert_changed(st, man, "forward_item", cols, uniq, ["id"], keep=("first_seen",), ignore=("first_seen", "last_checked"))[0]
            # an item the verifier dropped, or whose text changed (new id), is no longer held: status 'removed' instead of
            # staying open / verified in D1 (audit 26 Nov 2026). By id when the manifest knows the earlier rows; after a full
            # write (every row's last_checked is today) every row not written today.
            if old:
                gone = sorted(set(old) - {r[0] for r in uniq})
                _mark_gone(st, man, "forward_item", gone,
                           "UPDATE forward_item SET status = 'removed' WHERE status IS NOT 'removed' AND id IN ({})", old)
            elif n == len(uniq):
                st.q("UPDATE forward_item SET status = 'removed' WHERE last_checked < ? AND status IS NOT 'removed'", [d])
            return n

        def sheets():
            """narrativ_sheet: each stock's Narrativ sheet text, one row per write date (history of rewrites)."""
            sp = Path("data/story.json")
            stories = (json.loads(sp.read_text()) if sp.exists() else {}).get("stocks") or {}
            rows = [[isin[s], x.get("date"), s, x.get("what"), x.get("money"), [p["text"] if isinstance(p, dict) else p for p in x.get("plans") or []] or None, x.get("model")]
                    for s, x in stories.items() if s in isin and x.get("date")]
            return upsert_changed(st, man, "narrativ_sheet", ["isin", "date", "symbol", "what", "money", "plans", "model"], rows, ["isin", "date"])[0]

        def market():
            if not md:
                return 0
            return st.upsert("market_day", ["date", "mood_score", "zone", "inputs", "breadth_pct"],
                             [[d, md.get("score"), md.get("zone"), md.get("inputs"), (md.get("breadth") or {}).get("pct") if isinstance(md.get("breadth"), dict) else None]],
                             ["date"])

        def breadth():  # owner request 2026-11-23: industry breadth history for watching trends (not in the app)
            if not breadth_in:
                return 0
            from . import breadth as BR
            return BR.sync(st, today, *breadth_in,
                           upsert=lambda t, c, r, k: upsert_changed(st, man, t, c, r, k)[0])  # today's rows: reruns skip unchanged

        def document():
            """document: one row per document the pipeline knows (reader list, reader results, docling, research packs).
            Only rows whose content changed are sent."""
            return upsert_changed(st, man, "document", ["url", "isin", "date", "kind", "pages", "has_text", "text_key", "status"],
                                  document_rows(isin), ["url"], short=True)[0]

        def capped(fn, share=BACKFILL_SHARE):
            """Run a history backfill with at most `share` of the D1 rows left this run (counted as D1 rows written,
            indexes included), so it cannot starve what runs after it (audit 26 Nov 2026: the breadth backfill used the
            whole budget and events / quarters were not sent for days)."""
            def run_():
                b0 = st.budget
                st.budget = min(b0, st.rows_written + max(0, int((b0 - st.rows_written) * share)))
                try:
                    return fn()
                finally:
                    st.budget = b0
            return run_

        # daily essentials first (new events and filings included); the history backfills use what is left, each capped
        for name, fn in (("snapshot", snapshot), ("stock_detail", detail), ("market_day", market), ("research", research),
                         ("checkpoint", checkpoint), ("forward_item", forward), ("forward_signal", signals), ("narrativ_sheet", sheets), ("verdict_log", verdicts),
                         ("company", company), ("document", document), ("event", event), ("quarter", quarter),
                         ("industry_breadth", capped(breadth)), ("event_backfill", event_backfill)):
            step(name, fn)

        def r2():
            """R2: durable copies of the Actions-cache stores (DURABLE, DURABLE_DIRS), the daily price table, a daily copy of
            some git-side stores and the weekly memory backup. Each object is uploaded only when its content hash changed."""
            out = {}

            def put(key, h, make, ctype="application/gzip"):
                """Upload only when the content hash differs from what the manifest says is already in the bucket."""
                if man.r2_fresh(key, h):
                    out[key] = "unchanged"
                    return
                ok = st.put(key, make(), ctype)
                out[key] = ok
                if ok:
                    man.r2_done(key, h)

            def gzf(raw: bytes) -> bytes:
                return gzip.compress(raw, mtime=0)

            pk = Path("data/source_cache/prices.pkl")
            if pk.exists():
                put("prices/prices.parquet", "pq1-" + file_digest(pk), lambda: _prices_parquet(pk), "application/octet-stream")
            for f, key, how in DURABLE:
                p_ = Path(f)
                if p_.exists():
                    put(key, file_digest(p_), p_.read_bytes if how == "raw" else lambda p_=p_: gzf(p_.read_bytes()))
            for folder, key in DURABLE_DIRS:
                b = _bundle(Path(folder))
                if b is not None:
                    put(key, digest(b), lambda b=b: gzf(b))
            sv = Path("data/source_cache/surveillance.json")
            if sv.exists():  # one dated object a day (kept SURVEILLANCE_DAYS)
                put(f"nse/surveillance-{d}.json.gz", file_digest(sv), lambda: gzf(sv.read_bytes()))
            for f in ("analyst.json", "analyst_history.json", "classification.json", "bse_results.json"):  # git-side stores, daily copy
                p_ = Path("data") / f
                if p_.exists():
                    put(f"git/{f}.gz", file_digest(p_), lambda p_=p_: gzf(p_.read_bytes()))
            if today.weekday() == 0:  # weekly backup of the git-side JSON memory (kept BACKUPS_KEEP weeks)
                raw = json.dumps(mem, separators=(",", ":"), ensure_ascii=False, default=str).encode()
                put(f"backups/memory-{d}.json.gz", digest(raw), lambda: gzf(raw))
            return {k: v for k, v in out.items() if v != "unchanged"} | {"unchanged": sum(1 for v in out.values() if v == "unchanged")}
        step("r2", r2)

        def prune():
            if not man.due("r2_prune", PRUNE_EVERY_DAYS):
                return "not due"
            out, ok = prune_r2(st, today)
            if ok:
                man.did("r2_prune")
            return out
        step("r2_prune", prune)
        size = db_bytes(st)
        st.upsert("run_log", ["date", "stages", "counts", "usage"], [[d, stages, {**counts, **(extra_counts or {})},
                                                                     {**st.usage(), "utc_day": utc,
                                                                      "d1_rows_written_today": st.prior + st.rows_written,
                                                                      "db_bytes": size}]], ["date"], force=True)
    except Exception as e:  # noqa: BLE001
        print(f"[store] sync aborted: {e}")
    finally:
        try:  # dated objects are written once; only today's entry is worth remembering (a rerun skips it)
            man.data["r2"] = {k: v for k, v in man.data["r2"].items()
                              if not k.startswith(("nse/surveillance-", "backups/memory-")) or k.endswith(f"-{d}.json.gz")}
            man.save()
        except Exception as e:  # noqa: BLE001
            print(f"[store] manifest not saved: {e}")
    print(f"[store] {counts} usage {st.usage()} in {time.time() - t0:.0f}s")
    return {"ok": True, "counts": counts, "usage": st.usage()}


DB_WARN_BYTES = 250_000_000  # D1 Free: 500 MB per database; warn at half


def db_bytes(st) -> int | None:
    """The D1 database's size in bytes (Cloudflare API `file_size`, one read-only call a run); None when unknown.
    Logged in run_log.usage.db_bytes so the size is measured, not estimated (owner, 26 Nov 2026)."""
    if not getattr(st, "db", None):
        return None
    try:
        r = st.s.get(f"{st.base}/d1/database/{st.db}", timeout=30).json()
        size = (r.get("result") or {}).get("file_size")
        size = int(size) if size is not None else None
    except Exception as e:  # noqa: BLE001
        print(f"[store] D1 size not read: {e}")
        return None
    if size is not None and size > DB_WARN_BYTES:
        print(f"[store] WARNING: D1 database is {size / 1e6:.0f} MB (free limit 500 MB per database)")
    return size


def _prices_parquet(pk) -> bytes:
    """{symbol: OHLCV frame} pickle (local cache format) -> one long Parquet table: symbol, date, open, high, low, close, volume."""
    import io
    import pandas as pd
    store = pd.read_pickle(pk)
    frames = [df.assign(symbol=s).rename_axis("date").reset_index() for s, df in store.items() if len(df)]
    long = pd.concat(frames, ignore_index=True).rename(columns=str.lower)
    buf = io.BytesIO()
    long.to_parquet(buf, index=False, compression="zstd")
    return buf.getvalue()


def _bundle(folder: Path) -> bytes | None:
    """{file name: text} of a folder as canonical JSON bytes; None when the folder is missing or empty."""
    if not folder.is_dir():
        return None
    files = {f.name: f.read_text(errors="replace") for f in sorted(folder.iterdir()) if f.is_file()}
    return json.dumps(files, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode() if files else None


def _key_date(key: str) -> str | None:
    m = _DATED.search(key)
    return m[1] if m else None


def prune_r2(st: Store, today: date) -> tuple[dict, bool]:
    """Retention for dated R2 objects: surveillance snapshots older than SURVEILLANCE_DAYS, memory backups beyond the latest
    BACKUPS_KEEP. Deletes are free on R2; each listing page is one Class A operation. Returns (deleted counts, listings ok)."""
    out, ok = {}, True
    sv = st.list_keys("nse/surveillance-")
    if sv is None:
        ok = False
    else:
        cut = str(today - timedelta(days=SURVEILLANCE_DAYS))
        out["surveillance"] = sum(st.delete(k) for k in sv if (_key_date(k) or "9999") < cut)
    bk = st.list_keys("backups/memory-")
    if bk is None:
        ok = False
    else:
        dated = sorted((k for k in bk if _key_date(k)), key=_key_date)
        out["backups"] = sum(st.delete(k) for k in dated[:-BACKUPS_KEEP])
    return out, ok


def document_rows(isin: dict) -> list[list]:
    """Rows for the D1 `document` table from what the pipeline records about each document:
    data/reader/docs.json (documents to read: symbol, kind, date), data/reader/store.json (free-reader results),
    data/docling/index.json (layout / OCR conversion), docs/data/packs/*.json (pages, has_text of documents in Claude's queue)
    and the pypdf text cache data/source_cache/doctext/<sha1(url)>.txt / .pages (Actions cache).
      status: read (a free reader extracted rows) > converted (docling text in git) > failed (reader or docling error,
              nothing usable) > listed (known, not processed yet)
      text_key: data/docling/<sha1(url)>.md when docling text exists (git); NULL otherwise (the pypdf text is only cached)
      pages / has_text: NULL when no source recorded them."""
    docs: dict = {}

    def add(url, s=None, dt=None, kind=None, **kw):
        if not url:
            return
        e = docs.setdefault(url, {})
        for k, v in (("s", s), ("date", dt), ("kind", kind)):
            if v and not e.get(k):
                e[k] = v
        e.update({k: v for k, v in kw.items() if v is not None})

    for x in _json(Path("data/reader/docs.json")).get("docs") or []:
        add(x.get("url"), x.get("s"), x.get("date"), x.get("kind"))
    for u, e in _json(Path("data/reader/store.json")).items():
        ms = [e[m] for m in ("lite", "flash") if isinstance(e.get(m), dict)]
        read = any("rows" in m and not m.get("error") for m in ms)
        err = any(m.get("error") for m in ms)
        add(u, e.get("s"), e.get("date"), e.get("kind"), read=read or None, read_failed=(err and not read) or None,
            no_text=any("no text" in str(m.get("error") or "") for m in ms) or None)
    for u, e in _json(Path("data/docling/index.json")).items():
        add(u, e.get("s"), None, e.get("kind"), docling=bool(e.get("ok")))
    for f in sorted(Path("docs/data/packs").glob("*.json")):
        p = _json(f)
        for x in p.get("documents") or []:
            add(x.get("url"), p.get("symbol"), x.get("date"), x.get("kind"), pages=x.get("pages"), has_text=x.get("has_text"))
    txt = Path("data/source_cache/doctext")
    rows = []
    for u in sorted(docs):
        e = docs[u]
        h = hashlib.sha1(u.encode()).hexdigest()
        pages = e.get("pages")
        if pages is None and (txt / f"{h}.pages").exists():
            try:
                pages = int((txt / f"{h}.pages").read_text())
            except ValueError:
                pages = None
        md = Path("data/docling") / f"{h}.md"
        text_key = md.as_posix() if e.get("docling") and md.exists() else None
        has_text = e.get("has_text")
        if has_text is None:
            has_text = True if text_key or (txt / f"{h}.txt").exists() else (False if e.get("no_text") else None)
        status = ("read" if e.get("read") else "converted" if text_key else
                  "failed" if e.get("read_failed") or e.get("docling") is False else "listed")
        rows.append([u, isin.get(e.get("s")), e.get("date"), e.get("kind"), pages,
                     None if has_text is None else int(bool(has_text)), text_key, status])
    return rows


def restore_caches(only: set | None = None) -> None:
    """If the Actions cache was evicted, pull the stores back from R2: prices, every DURABLE file, every DURABLE_DIRS folder.
    `only`: restore just these local paths (e.g. {"data/news_cache/news.json.gz"})."""
    st = None

    def want(p) -> bool:
        return only is None or str(p) in only

    pk = Path("data/source_cache/prices.pkl")
    if want(pk) and not pk.exists():
        import io
        import pandas as pd
        st = st or Store()
        data = st.get("prices/prices.parquet")
        if data:
            long = pd.read_parquet(io.BytesIO(data))
            cols = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
            store = {s: g.set_index("date")[list(cols)].rename(columns=cols) for s, g in long.groupby("symbol")}
            pk.parent.mkdir(parents=True, exist_ok=True)
            pd.to_pickle(store, pk)
            print(f"[store] restored prices for {len(store)} symbols from R2")
    for f, key, how in DURABLE:
        p_ = Path(f)
        if not want(f) or p_.exists():
            continue
        st = st or Store()
        data = st.get(key)
        if not data:
            continue
        try:
            raw = data if how == "raw" else gzip.decompress(data)
        except OSError as e:
            print(f"[store] R2 {key} unreadable: {e}")
            continue
        p_.parent.mkdir(parents=True, exist_ok=True)
        p_.write_bytes(raw)
        print(f"[store] restored {f} from R2 ({len(raw) / 1e6:.1f} MB)")
    for folder, key in DURABLE_DIRS:
        d_ = Path(folder)
        if not want(folder) or (d_.is_dir() and any(d_.iterdir())):
            continue
        st = st or Store()
        data = st.get(key)
        if not data:
            continue
        try:
            files = json.loads(gzip.decompress(data))
        except (OSError, ValueError) as e:
            print(f"[store] R2 {key} unreadable: {e}")
            continue
        d_.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (d_ / Path(name).name).write_text(text)
        print(f"[store] restored {len(files)} files into {folder} from R2")


# ---------------------------------------------------------------- D1 after the publish (data-branch plan §2.6)
# With DEFER_D1=1 the daily run does not write D1 itself: it saves the sync inputs (defer), and the workflow runs
# `python -m narrativ.dbsync --deferred` after the publish gate passed and the data was pushed, so a build the gate refused
# never reaches D1. The file is the run's own in-memory inputs, written and read in the same job on the runner's temp disk
# (never committed, never downloaded). Without DEFER_D1 run.py calls sync() as before.
def _defer_path() -> Path:
    return Path(os.environ.get("D1_DEFER_FILE") or os.path.join(os.environ.get("RUNNER_TEMP") or "data/exchange_tmp",
                                                                   "d1_deferred.pkl"))


def deferred() -> bool:
    return os.environ.get("DEFER_D1") == "1"


def defer(args: tuple, kwargs: dict) -> Path:
    p = _defer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        pickle.dump((args, kwargs), f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[store] D1 sync deferred to after the publish ({p}, {p.stat().st_size / 1e6:.0f} MB)")
    return p


def run_deferred() -> dict:
    """The deferred sync; never raises (D1 is not the app's source). The inputs file is removed after the attempt."""
    p = _defer_path()
    if not p.exists():
        print("[store] no deferred D1 sync (the run did not reach it)")
        return {"ok": False}
    try:
        with p.open("rb") as f:
            args, kwargs = pickle.load(f)  # noqa: S301 - written by this job's own run.py (defer) on the runner
        return sync(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        print(f"[store] deferred sync failed: {type(e).__name__}: {str(e)[:200]}")
        return {"ok": False}
    finally:
        p.unlink(missing_ok=True)


if __name__ == "__main__":
    if "--deferred" in sys.argv:
        run_deferred()
    sys.exit(0)
