import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


def download(symbols: list[str], period: str = "2y", chunk: int = 80, min_rows: int = 5) -> dict[str, pd.DataFrame]:
    """Batch-download daily OHLCV. Returns {symbol: df} with columns Open High Low Close Volume."""
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), chunk):
        batch = symbols[i : i + chunk]
        for attempt in range(3):
            try:
                data = yf.download(
                    batch, period=period, interval="1d", group_by="ticker",
                    auto_adjust=True, progress=False, threads=True,
                )
                break
            except Exception as e:  # noqa: BLE001
                print(f"[prices] retry {attempt + 1}: {e}")
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for s in batch:
            try:
                df = data[s] if isinstance(data.columns, pd.MultiIndex) else data
                df = df.dropna(subset=["Close"])
                if len(df) >= min_rows:  # recent listings kept (16 Nov: 82 stocks under 61 days had no price at all); technicals still need 210
                    out[s] = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            except KeyError:
                pass
        time.sleep(0.5)
    return out


STORE = Path("data/source_cache/prices.pkl")  # kept in the Actions cache, never in git
META = Path("data/source_cache/prices_meta.json")  # {"miss": {symbol: last Yahoo try}, "adj": [recent adjustments]}
MISS_RETRY_DAYS = 7
WINDOW_DAYS = 10      # calendar days of exchange files re-read each run (fills missed days, picks up corrections)
TOL = 0.005           # stored close vs exchange previous close; beyond this the history is re-based


def _ist_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()


def _bse_codes() -> dict:
    try:
        u = json.loads(Path("data/universe_exchange.json").read_text())["stocks"]
        return {s: v[1] for s, v in u.items() if s.endswith(".BO") and v and len(v) > 1 and v[1]}
    except Exception:  # noqa: BLE001
        return {}


def download_cached(symbols: list[str], period: str = "5y", **_) -> dict[str, pd.DataFrame]:
    """Daily prices from the exchanges' end-of-day files; Yahoo only to seed a symbol's history once.

    Each run re-reads the last WINDOW_DAYS of NSE / BSE / index files (cached; normally only today's are downloaded)
    and writes one bar per stock per day. Before writing a day, the stored previous close is compared with the
    exchange's PREV_CLOSE, which NSE and BSE adjust for splits, bonus and rights: a gap beyond TOL re-bases the stored
    history by that ratio (prices x ratio, volume / ratio). Nothing is re-downloaded for corporate actions.
    Yahoo is used only for symbols with no stored history (new to the universe) or a gap longer than the window;
    symbols Yahoo has nothing for are retried weekly. Ordinary dividends are not adjusted (as on the exchanges)."""
    from .bhav import bse as bse_day, index as idx_day, nse as nse_day
    from .filings import NSESession
    store: dict[str, pd.DataFrame] = {}
    if STORE.exists():
        try:
            store = pd.read_pickle(STORE)
        except Exception as e:  # noqa: BLE001
            print(f"[prices] store unreadable, full fetch: {e}")
    try:
        meta = json.loads(META.read_text()) if META.exists() else {}
    except Exception:  # noqa: BLE001
        meta = {}
    miss = meta.setdefault("miss", {})
    t0 = time.time()
    today = _ist_today()
    codes = _bse_codes()
    try:
        ns = NSESession()
    except Exception as e:  # noqa: BLE001
        print(f"[prices] NSE session failed: {e}")
        ns = None
    def _date(x):
        for f in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(x).strip().title(), f).date()
            except ValueError:
                continue
        return None

    files = {}
    for d in [today - timedelta(days=i) for i in range(WINDOW_DAYS, -1, -1)]:
        if not ns:  # weekends included: special sessions (Diwali Muhurat trading) happen on them
            continue
        n = nse_day(ns, d)
        td = _date((n or {}).get("_date"))
        if not n or not td or td in files:
            continue  # holiday, not published yet, failed, or a repeat of an earlier day's file
        b = bse_day(d) or {}
        ix = idx_day(ns, d)
        files[td] = (n, b if _date(b.get("_date")) == td else {}, ix[1] if ix and _date(ix[0]) == td else None)
    w0 = pd.Timestamp(min(files)) if files else None
    applied = set(meta.get("applied", []))
    seeded, actions, aligned, written = [], [], [], 0
    syms = list(dict.fromkeys(symbols))

    def bar(sym, n, b, ix):
        if sym == "^NSEI":
            return ix
        if sym.endswith(".NS"):
            return n.get(sym[:-3])
        return b.get(str(codes.get(sym))) if sym.endswith(".BO") else None

    need_yahoo = []
    cols4 = ["Open", "High", "Low", "Close"]
    for sym in syms:
        df = store.get(sym)
        if df is None or not len(df) or w0 is None or df.index[-1] < w0 - pd.Timedelta(days=WINDOW_DAYS):
            if (today - date.fromisoformat(miss.get(sym, "2000-01-01"))).days >= MISS_RETRY_DAYS:
                need_yahoo.append(sym)
            continue
        raw = {d: bar(sym, *files[d]) for d in sorted(files)}
        raw = {d: x for d, x in raw.items() if x and x[3]}
        if not raw:
            continue
        old = df[df.index < w0].astype("float64")  # history before the window: final, rewritten only by an adjustment
        wd = sorted(raw)
        events = []  # (date, ratio): exchange previous close vs our previous close
        for i, d in enumerate(wd):
            pc = raw[d][5]
            if not pc:
                continue
            if i:
                base, seam = raw[wd[i - 1]][3], False
            elif len(old):
                base, seam = float(old["Close"].iloc[-1]), old.index[-1] < pd.Timestamp(meta.get("since", "2100-01-01"))
            else:
                continue
            if base and abs(pc / base - 1) > TOL:
                events.append((d, pc / base, seam))
        for d, k, seam in events:
            key = f"{sym}|{d.isoformat()}"
            if key not in applied:  # stored history before the window: adjusted once (later bars are written adjusted)
                if len(old):
                    old.loc[:, cols4] = old[cols4] * k
                    old.loc[:, "Volume"] = old["Volume"] / k
                applied.add(key)
                (aligned if seam else actions).append([sym, d.isoformat(), round(k, 4)])
        rows = []
        for d in wd:
            o, h, lo, c, v, _ = raw[d]
            k = 1.0
            for e, r, _s in events:  # window bars before an ex-date get that ratio, every run (they are re-read raw)
                if d < e:
                    k *= r
            rows.append([(o or c) * k, (h or c) * k, (lo or c) * k, c * k, v / k])
        new = pd.DataFrame(rows, columns=cols4 + ["Volume"], index=pd.DatetimeIndex([pd.Timestamp(d) for d in wd]))
        store[sym] = pd.concat([old, new])
        written += len(rows)
    meta.setdefault("since", min(files).isoformat() if files else None)
    meta["applied"] = sorted(applied)[-5000:]
    if need_yahoo:
        got = download(need_yahoo, period=period)
        for sym in need_yahoo:
            if sym in got:
                store[sym] = got[sym]
                miss.pop(sym, None)
                seeded.append(sym)
            else:
                miss[sym] = today.isoformat()
    cut = pd.Timestamp(today) - pd.Timedelta(days=5 * 366)
    out = {s: store[s][store[s].index >= cut].astype("float32") for s in syms if s in store}
    STORE.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle({**store, **out}, STORE)
    meta["adj"] = (actions + meta.get("adj", []))[:200]
    meta["last_file"] = max(files).isoformat() if files else meta.get("last_file")
    META.write_text(json.dumps(meta))
    print(f"[prices] exchange files for {len(files)} days (latest {max(files) if files else '–'}), {written} bars written, "
          f"{len(actions)} re-based for corporate actions{(': ' + ', '.join(f'{a[0]} {a[1]} x{a[2]}' for a in actions[:10])) if actions else ''}, "
          f"{len(aligned)} aligned to the exchange at the first switch, "
          f"{len(seeded)} seeded from Yahoo, {sum(1 for s in need_yahoo if s not in seeded)} without data (retried weekly), {time.time() - t0:.0f}s")
    if not files or (max(files) < today and today.weekday() < 5):
        print(f"[prices] today's exchange file not published yet (latest {max(files) if files else '–'})")
    return {s: d.astype("float64") for s, d in out.items()}


def _download_long(symbols: list[str], period: str) -> dict[str, pd.DataFrame]:
    """download() keeps only series longer than 60 rows; for new listings that is fine (technicals need it too)."""
    return download(symbols, period=period)


def extra_prices(universe: set[str], bench_close: pd.Series) -> dict:
    """docs/data/extra_prices.json: the latest NSE close of every symbol in the exchange file that is not a scored stock
    (ETFs such as GOLDBEES, SILVER; other series), plus the Nifty 50, for the app's Portfolio (owner's holdings are priced
    on the phone; nothing about them is stored here). Read from the cached NSE end-of-day file, no download."""
    import csv
    import io
    from .bhav import DIR, _f
    files = sorted((f for f in DIR.glob("nse_*.csv") if f.stat().st_size > 0), reverse=True)
    if not files:
        return {}
    rd = csv.reader(io.StringIO(files[0].read_text()))
    head = [h.strip() for h in next(rd, [])]
    ix = {h: i for i, h in enumerate(head)}
    if "CLOSE_PRICE" not in ix:
        return {}
    px, ser, fdate = {}, {}, None
    for row in rd:  # every series (ETFs are not always EQ); EQ preferred when a symbol has several
        row = [c.strip() for c in row]
        if len(row) < len(head):
            continue
        sym, se = row[ix["SYMBOL"]], row[ix["SERIES"]]
        fdate = fdate or (row[ix["DATE1"]] if "DATE1" in ix else None)
        if f"{sym}.NS" in universe or (sym in ser and (ser[sym] == "EQ" or se != "EQ")):
            continue
        close, prev = _f(row[ix["CLOSE_PRICE"]]), _f(row[ix["PREV_CLOSE"]])
        if close:
            px[sym], ser[sym] = [round(close, 2), round((close / prev - 1) * 100, 2) if prev else None], se
    b = bench_close.dropna()
    if len(b) >= 2:
        px["NIFTY 50"] = [round(float(b.iloc[-1]), 2), round((float(b.iloc[-1]) / float(b.iloc[-2]) - 1) * 100, 2)]
    out = {"date": fdate or files[0].stem[4:], "note": "Latest NSE close and day change (%) of listed symbols that are not scored stocks (ETFs etc.), and the Nifty 50.",
           "prices": px}
    Path("docs/data/extra_prices.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"[prices] extra prices for {len(px)} symbols (ETFs and others) from {out['date']}")
    return out
