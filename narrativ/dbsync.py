"""Daily run -> D1 tables + R2 files. Called at the end of run.py; never fatal."""
import gzip
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from . import events as EV
from .store import Store, gz
from .util import digest, file_digest, write_if_changed

CR = 1e7
MANIFEST = Path("data/d1_manifest.json")  # content hash of every row / object already written; committed with the daily data
REFRESH_DAYS = int(os.environ.get("D1_REFRESH_DAYS", "7"))  # a table or object older than this is rewritten in full (self-heals drift)


def _cr(x):
    return None if x is None else round(x / CR, 2)



class Manifest:
    """What the last successful syncs wrote, as content hashes: {"schema": h, "tables": {t: {"at": date, "h": {key: hash}}}, "r2": {key: [hash, date]}}.

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

    def set_rows(self, table: str, h: dict, full: bool) -> None:
        prev = self.data["tables"].get(table) or {}
        self.data["tables"][table] = {"at": str(self.today) if full else prev.get("at") or str(self.today), "h": h}
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
                   ignore: tuple = (), hash_of=None) -> tuple[int, int]:
    """Upsert only the rows whose content hash differs from the manifest (all rows when the manifest has nothing for the table).

    `ignore` columns are left out of the hash (volatile values that alone are not worth a write; they ride along when the row
    is written for another reason). `hash_of(row)` replaces the column-based hash when a single field of a JSON column is volatile.
    Returns (rows sent, rows unchanged and skipped)."""
    kidx = [cols.index(k) for k in keys]
    hidx = [i for i, c in enumerate(cols) if c not in ignore]
    old = man.rows(table)
    new, todo = {}, []
    for r in rows:
        k = "|".join(str(r[i]) for i in kidx)
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
    man.set_rows(table, final, full=not old and len(ok) == len(todo))
    if err:
        raise err
    return len(ok), len(rows) - len(todo)


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
        for tb in list(man.data["tables"]):
            try:
                if st.count(tb) < len(man.data["tables"][tb].get("h") or {}):
                    print(f"[store] {tb}: D1 holds fewer rows than the manifest; full resend")
                    man.drop(tb)
            except Exception as e:  # noqa: BLE001  (table missing: database was recreated)
                print(f"[store] manifest distrusted ({tb}: {e}); full sync")
                man.drop()
                break
        fp = Store.schema_fingerprint(repr(SNAP_NEW))
        if man.data.get("schema") == fp:
            print("[store] schema unchanged since the last sync; skipping apply_schema")
        else:
            st.apply_schema()
            try:  # daily decision history (for backtesting the rules): columns added after the table was created
                have = {r.get("name") for r in st.q("PRAGMA table_info(snapshot)")}
                for c, t in SNAP_NEW:
                    if have and c not in have:
                        st.q(f"ALTER TABLE snapshot ADD COLUMN {c} {t}")
                man.data["schema"] = fp
                man.dirty = True
            except Exception as e:  # noqa: BLE001
                print(f"[store] snapshot columns: {e}")
        try:  # a second run on the same UTC day shares the 100k/day D1 limit with the first
            prev = st.q("SELECT usage FROM run_log WHERE date = ?", [d])
            u0 = json.loads(prev[0]["usage"]) if prev else {}
            done = int(u0.get("d1_rows_written_today", u0.get("d1_rows_written", 0)))
            st.prior = done
            if done:
                st.budget = max(2_000, min(st.budget, 95_000 - done))
                print(f"[store] {done} rows already written today; budget {st.budget}")
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
                gone = sorted(set(trusted) - set(isin.values()))
                for k in range(0, len(gone), 500):
                    st.q("UPDATE company SET in_universe = 0 WHERE isin IN (" + ",".join("?" * len(gone[k:k + 500])) + ")", gone[k:k + 500])
            else:
                st.q("UPDATE company SET in_universe = 0 WHERE last_seen < ?", [d])
            return n

        def quarter():
            # new filings every day; companies with nothing stored yet are backfilled inside the remaining budget
            have = {r["isin"] for r in st.q("SELECT DISTINCT isin FROM quarter")}
            # re-read since the last sync (daily run or a side job such as the filings catch-up / history re-read)
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
            return st.upsert("quarter", ["isin", "period_end", "basis", "kind", "revenue_cr", "ebitda_cr", "pat_cr", "pat_owners_cr", "eps",
                                         "equity_cr", "borrowings_cr", "cash_cr", "extra", "filed_on", "audited", "source_url"], rows,
                             ["isin", "period_end", "basis"])

        def snapshot():
            rows = []
            for p in picks:
                i = isin.get(p["s"])
                if not i:
                    continue
                t, sc = (p.get("t") or [None] * 7), (p.get("sc") or [None] * 7)
                rows.append([i, d, p.get("p"), p.get("mc"), p.get("d1"), *t[:7], *sc[:7], p.get("vd"), p.get("pr"), p.get("su") or p.get("ss"),
                             (p.get("out") or {}).get("l"), (p.get("out") or {}).get("w"),
                             p.get("dc"), p.get("cand"), p.get("vf"), p.get("rk"), 1 if p.get("mb") else 0, p.get("cv")])
            n = st.upsert("snapshot", ["isin", "date", "price", "mcap_cr", "chg_1d", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
                                       "s1", "s2", "s3", "s4", "s5", "s6", "s7", "verdict", "priority", "setup", "removed_level", "removed_reason",
                                       *[c for c, _ in SNAP_NEW]],
                          rows, ["isin", "date"])
            # retention (decision 1-b): daily for 365 days, then Mondays only
            st.q("DELETE FROM snapshot WHERE date < ? AND strftime('%w', date) != '1'", [str(today - timedelta(days=365))])
            return n

        def detail():
            # the readiness rank (rk) reshuffles for ~every stock daily and is in the snapshot table; it alone no longer
            # rewrites a ~16 KB row. `date` is the day the row was last written (a full refresh runs every REFRESH_DAYS).
            rows = [[isin[p["s"]], d, p, details.get(p["s"])] for p in picks if p["s"] in isin]
            return upsert_changed(st, man, "stock_detail", ["isin", "date", "pick", "detail"], rows, ["isin"], ignore=("date",),
                                  hash_of=lambda r: [r[0], {k: v for k, v in r[2].items() if k != "rk"}, r[3]])[0]

        def event():
            # daily: the last 3 days; plus a gradual backfill of older history (newest first) inside the write budget.
            # D1 counts each index update as a written row, so one event costs ~3 rows.
            r = st.q("SELECT MIN(date) AS m FROM event WHERE exchange = 'NSE'")
            oldest = (r[0]["m"] if r and r[0]["m"] else "9999")
            recent = str(today - timedelta(days=3))
            rows, seen = [], set()
            for s, rs in (ann_st.get("rows") or {}).items():
                i = isin.get(s)
                if not i:
                    continue
                for dt, cat, txt, url, g, rule in rs:
                    if dt < recent and dt > oldest:  # the oldest stored day is re-sent: heals a day cut short by the budget
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
                    if (e.get("date") or "") < recent:
                        continue
                    k = e.get("url") or f"BSE|{i}|{e.get('date')}|{(e.get('text') or '')[:80]}"
                    if k not in seen:
                        seen.add(k)
                        rows.append([k, i, s, e.get("date"), "BSE", e.get("category"), e.get("text"), None, None, e.get("sev"), e.get("type"), e.get("url"), d])
            rows.sort(key=lambda r: r[3] or "", reverse=True)
            cols = ["id", "isin", "symbol", "date", "exchange", "category", "subject", "doc_group", "rule", "severity", "type", "url", "first_seen"]
            new = [r for r in rows if (r[3] or "") >= recent]
            old = [r for r in rows if (r[3] or "") < recent]
            w0 = st.rows_written
            sent = st.upsert("event", cols, new, ["id"], keep=("first_seen",))
            cost = (st.rows_written - w0) / sent if sent else 4.0  # D1 rows written per event, indexes included
            # backfill whole days only (newest first), each day only if it fits, so MIN(date) is always a clean boundary
            stop = min(st.budget, 95_000 - st.prior) - 2_000
            days: dict = {}
            for r in old:
                days.setdefault(r[3], []).append(r)
            back = 0
            for dt in sorted(days, reverse=True):
                if st.rows_written + len(days[dt]) * cost * 1.2 > stop:
                    break
                back += st.upsert("event", cols, days[dt], ["id"], keep=("first_seen",))
            print(f"[store] events: {sent} recent + {back} backfill (of {len(old)} older; oldest stored {oldest}; {cost:.1f} D1 rows per event)")
            return sent + back

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

        def verdicts():
            full = st.count("verdict_log") < 100
            rows = []
            for s, rec in mem.items():
                i = isin.get(s)
                for v in (rec.get("verdicts") or []) if i else []:
                    if full or v.get("d") == d:
                        rows.append([i, v.get("d"), v.get("from"), v.get("v"), None, rec.get("tiers")])
            return st.upsert("verdict_log", ["isin", "date", "verdict_from", "verdict_to", "priority", "tiers"], rows, ["isin", "date"])

        def research():
            rows = [[isin[s], s, t.get("updated"), t.get("quarter"), t.get("source_type"), t.get("outlook_score"),
                     {k: v for k, v in t.items() if k != "scan_raw"}] for s, t in theses.items() if s in isin]
            return upsert_changed(st, man, "research", ["isin", "symbol", "updated", "quarter", "source_type", "outlook_score", "thesis"], rows, ["isin"])[0]

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
            return BR.sync(st, today, *breadth_in)

        # daily essentials first; the big one-off backfills (events, quarters, breadth history) use what is left of the budget
        for name, fn in (("snapshot", snapshot), ("stock_detail", detail), ("market_day", market), ("research", research),
                         ("checkpoint", checkpoint), ("verdict_log", verdicts), ("company", company), ("industry_breadth", breadth),
                         ("event", event), ("quarter", quarter)):
            step(name, fn)

        # R2: the two stores that today live only in the Actions cache (evicted after 7 days unused)
        def r2():
            out = {}

            def put(key, h, make, ctype="application/octet-stream"):
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
                put("prices/prices.parquet", "pq1-" + file_digest(pk), lambda: _prices_parquet(pk))
            for f, key in (("announcements.json.gz", "announcements/store.json.gz"), ("bse_announcements.json.gz", "announcements/bse_store.json.gz")):
                p_ = Path("data/source_cache") / f
                if p_.exists():
                    put(key, file_digest(p_), p_.read_bytes, "application/gzip")
            for f, key in (("delivery.json", "nse/delivery.json.gz"), ("surveillance.json", f"nse/surveillance-{d}.json.gz"), ("indices.json", "nse/indices.json.gz"), ("shp.json", "nse/shp.json.gz"), ("corpfil.json", "nse/corpfil.json.gz"),
                           ("prices_meta.json", "prices/prices_meta.json.gz"), ("index_hist.json", "nse/index_hist.json.gz"),
                           ("bulk_deals.json", "nse/bulk_deals.json.gz")):
                p_ = Path("data/source_cache") / f
                if p_.exists():
                    raw = p_.read_bytes()
                    put(key, digest(raw), lambda raw=raw: gzf(raw), "application/gzip")
            for f in ("analyst.json", "analyst_history.json", "classification.json", "bse_results.json"):  # git-side stores, daily copy
                p_ = Path("data") / f
                if p_.exists():
                    raw = p_.read_bytes()
                    put(f"git/{f}.gz", digest(raw), lambda raw=raw: gzf(raw), "application/gzip")
            if today.weekday() == 0:  # weekly backup of the git-side JSON memory (D1 export comes later)
                out["backup"] = st.put(f"backups/memory-{d}.json.gz", gz(mem))
            return {k: v for k, v in out.items() if v != "unchanged"} | {"unchanged": sum(1 for v in out.values() if v == "unchanged")}
        step("r2", r2)
        st.upsert("run_log", ["date", "stages", "counts", "usage"], [[d, stages, {**counts, **(extra_counts or {})},
                                                                     {**st.usage(), "d1_rows_written_today": st.prior + st.rows_written}]], ["date"], force=True)
    except Exception as e:  # noqa: BLE001
        print(f"[store] sync aborted: {e}")
    finally:
        try:
            man.data["r2"] = {k: v for k, v in man.data["r2"].items() if not k.startswith("nse/surveillance-") or k.endswith(f"-{d}.json.gz")}
            man.save()
        except Exception as e:  # noqa: BLE001
            print(f"[store] manifest not saved: {e}")
    print(f"[store] {counts} usage {st.usage()} in {time.time() - t0:.0f}s")
    return {"ok": True, "counts": counts, "usage": st.usage()}


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


def restore_caches() -> None:
    """If the Actions cache was evicted, pull the price and announcement stores back from R2."""
    import io
    from pathlib import Path
    import pandas as pd
    st = None
    pk = Path("data/source_cache/prices.pkl")
    if not pk.exists():
        st = st or Store()
        data = st.get("prices/prices.parquet")
        if data:
            long = pd.read_parquet(io.BytesIO(data))
            cols = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
            store = {s: g.set_index("date")[list(cols)].rename(columns=cols) for s, g in long.groupby("symbol")}
            pk.parent.mkdir(parents=True, exist_ok=True)
            pd.to_pickle(store, pk)
            print(f"[store] restored prices for {len(store)} symbols from R2")
    an = Path("data/source_cache/announcements.json.gz")
    if not an.exists():
        st = st or Store()
        data = st.get("announcements/store.json.gz")
        if data:
            an.parent.mkdir(parents=True, exist_ok=True)
            an.write_bytes(data)
            print(f"[store] restored announcement store from R2 ({len(data) / 1e6:.1f} MB)")
    bse_an = Path("data/source_cache/bse_announcements.json.gz")
    if not bse_an.exists():
        st = st or Store()
        data = st.get("announcements/bse_store.json.gz")
        if data:
            bse_an.parent.mkdir(parents=True, exist_ok=True)
            bse_an.write_bytes(data)
            print("[store] restored BSE announcement store from R2")
    pm = Path("data/source_cache/prices_meta.json")  # corporate-action adjustments already applied: must travel with prices
    if not pm.exists():
        st = st or Store()
        data = st.get("prices/prices_meta.json.gz")
        if data:
            pm.parent.mkdir(parents=True, exist_ok=True)
            pm.write_bytes(gzip.decompress(data))
            print("[store] restored price adjustment log from R2")
    for f in ("delivery.json", "indices.json", "shp.json", "corpfil.json", "index_hist.json", "bulk_deals.json"):  # NSE daily-file and shareholding stores
        p_ = Path("data/source_cache") / f
        if not p_.exists():
            st = st or Store()
            data = st.get(f"nse/{f}.gz")
            if data:
                p_.parent.mkdir(parents=True, exist_ok=True)
                p_.write_bytes(gzip.decompress(data))
                print(f"[store] restored {f} from R2")
