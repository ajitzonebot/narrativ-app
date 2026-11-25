"""Cloudflare D1 (tables) + R2 (files) writer for the daily run. Uses the CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID secrets.

Never fatal: any failure is logged and the run continues (git JSON stays the fallback during the switch-over).
Write budget: D1 Workers Free allows 100,000 rows written a day; this module stops at WRITE_BUDGET and logs usage.
"""
import gzip
import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

API = "https://api.cloudflare.com/client/v4/accounts/{acc}"
DB_NAME, BUCKET = "narrativ", "narrativ-data"
SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
MAX_SQL = 90_000          # D1 limit is 100 KB per statement
WRITE_BUDGET = 60_000     # of 100,000 rows/day on Workers Free
WORKERS = max(1, int(os.environ.get("D1_WORKERS", "3")))  # concurrent statements per upsert (1 = strictly sequential)


def _lit(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(float(v)) if isinstance(v, float) else str(v)
    if not isinstance(v, str):
        v = json.dumps(v, separators=(",", ":"), ensure_ascii=False, default=str)
    return "'" + v.replace("\x00", "").replace("'", "''") + "'"


class Store:
    def __init__(self):
        tok = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        acc = "".join(os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").split()).strip("\"'")
        self.ok = bool(tok and acc)
        self.budget = WRITE_BUDGET
        self.prior = 0  # rows written by earlier runs the same day
        self.base = API.format(acc=acc)
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {tok}"})
        self.rows_written = self.calls = 0
        self.lock = threading.Lock()
        self.r2_puts = self.r2_bytes = self.r2_deletes = 0
        self.db = None
        if self.ok:
            try:
                r = self.s.get(f"{self.base}/d1/database", params={"name": DB_NAME}, timeout=30).json()
                self.db = next((d["uuid"] for d in r.get("result") or [] if d.get("name") == DB_NAME), None)
            except Exception as e:  # noqa: BLE001
                print(f"[store] D1 lookup failed: {e}")
        if not self.db:
            print("[store] D1 not available (no token or database); skipping table writes")

    # ---------- D1 ----------
    def q(self, sql: str, params: list | None = None) -> list:
        if not self.db:
            return []
        for i in range(3):
            try:
                r = self.s.post(f"{self.base}/d1/database/{self.db}/query", json={"sql": sql, "params": params or []}, timeout=60)
                js = r.json()
                with self.lock:
                    self.calls += 1
                if js.get("success"):
                    res = js.get("result") or []
                    with self.lock:
                        self.rows_written += sum((x.get("meta") or {}).get("rows_written", 0) for x in res)
                    return [row for x in res for row in (x.get("results") or [])]
                if r.status_code in (429, 500, 502, 503):
                    time.sleep(2 * (i + 1))
                    continue
                raise RuntimeError(str(js.get("errors"))[:300])
            except requests.RequestException:
                time.sleep(2 * (i + 1))
        raise RuntimeError("D1 query failed after retries")

    @staticmethod
    def _schema_statements() -> list[str]:
        sql = "\n".join(re.sub(r"--.*$", "", l) for l in SCHEMA.read_text().splitlines())  # schema has no '--' inside strings
        return [s.strip() for s in sql.split(";") if s.strip()]

    @classmethod
    def schema_fingerprint(cls, extra: str = "") -> str:
        """Hash of the schema statements (comments ignored): unchanged hash means apply_schema can be skipped."""
        return hashlib.sha1(("\n;\n".join(cls._schema_statements()) + extra).encode()).hexdigest()[:16]

    def apply_schema(self) -> None:
        for stmt in self._schema_statements():
            self.q(stmt)

    def upsert(self, table: str, cols: list[str], rows: list[list], keys: list[str], keep: tuple = (), force: bool = False,
               on_sent=None) -> int:
        """Multi-row INSERT ... ON CONFLICT DO UPDATE, packed under the statement-size limit. Returns rows sent.

        Statements are independent, so up to WORKERS run at once. `on_sent(indices)` is called (from the calling thread) with the
        positions in `rows` of every statement that D1 accepted, so a caller can record exactly what was written even if a
        later statement fails. The daily write budget counts rows still in flight, so concurrency cannot overshoot it by more
        than the statements already submitted."""
        if not self.db or not rows:
            return 0
        upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in keys and c not in keep)
        head = f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
        tail = f" ON CONFLICT ({', '.join(keys)}) DO " + (f"UPDATE SET {upd}" if upd else "NOTHING")
        one = "(" + ",".join("?" * len(cols)) + ")"
        sent = 0
        pending: deque = deque()  # (future, row indices)
        pool = ThreadPoolExecutor(WORKERS) if WORKERS > 1 else None
        err: Exception | None = None

        def settle(limit: int) -> None:
            nonlocal sent, err
            while len(pending) > limit:
                fut, idx = pending.popleft()
                try:
                    fut.result()
                except Exception as e:  # noqa: BLE001
                    err = err or e
                    continue
                sent += len(idx)
                if on_sent:
                    on_sent(idx)

        def submit(sql: str, params, idx: list[int]) -> None:
            nonlocal sent, err
            if pool is None:
                try:
                    self.q(sql, params)
                except Exception as e:  # noqa: BLE001
                    err = err or e
                    return
                sent += len(idx)
                if on_sent:
                    on_sent(idx)
                return
            pending.append((pool.submit(self.q, sql, params), idx))
            settle(WORKERS - 1)  # bounded: wait for the oldest once WORKERS statements are in flight

        def exhausted() -> bool:
            inflight = sum(len(i) for _, i in pending)
            return not force and self.rows_written + inflight >= self.budget

        buf, bidx, size = [], [], len(head) + len(tail)
        try:
            for n, r in enumerate(rows):
                if err:
                    break
                if exhausted():
                    print(f"[store] write budget reached in {table}; {len(rows) - sent - len(buf)} rows left for tomorrow")
                    break
                v = "(" + ",".join(_lit(x) for x in r) + ")"
                if len(v) + len(head) + len(tail) > MAX_SQL:  # one huge row: bind it instead of inlining
                    submit(head + one + tail,
                           [x if isinstance(x, (str, int, float)) or x is None else json.dumps(x, ensure_ascii=False, default=str) for x in r], [n])
                    continue
                if size + len(v) + 1 > MAX_SQL:
                    submit(head + ",".join(buf) + tail, None, bidx)
                    buf, bidx, size = [], [], len(head) + len(tail)
                    if exhausted():  # the flush above may have used up the budget
                        print(f"[store] write budget reached in {table}; rows after #{n} left for tomorrow")
                        break
                buf.append(v)
                bidx.append(n)
                size += len(v) + 1
            if buf and not err and (force or self.rows_written + sum(len(i) for _, i in pending) < self.budget):
                submit(head + ",".join(buf) + tail, None, bidx)
        finally:
            settle(0)
            if pool:
                pool.shutdown()
        if err:
            raise err
        return sent

    def count(self, table: str) -> int:
        """Rows in a table. D1 bills this as one row read per row: use probe() on big tables."""
        r = self.q(f"SELECT COUNT(*) AS n FROM {table}")
        return int(r[0]["n"]) if r else 0

    def probe(self, table: str, cols, keys: list) -> int:
        """How many of these primary keys (value lists in `cols` order) exist: primary-key lookups, a few rows read."""
        if not keys:
            return 0
        where = " OR ".join("(" + " AND ".join(f"{c} = ?" for c in cols) + ")" for _ in keys)
        r = self.q(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", [v for k in keys for v in k])
        return int(r[0]["n"]) if r else 0

    # ---------- R2 ----------
    def put(self, key: str, data: bytes, ctype: str = "application/octet-stream") -> bool:
        if not self.ok:
            return False
        try:
            r = self.s.put(f"{self.base}/r2/buckets/{BUCKET}/objects/{key}", data=data, headers={"Content-Type": ctype}, timeout=300)
            if r.ok:
                self.r2_puts += 1
                self.r2_bytes += len(data)
                return True
            print(f"[store] R2 put {key}: http {r.status_code} {r.text[:160]}")
        except Exception as e:  # noqa: BLE001
            print(f"[store] R2 put {key}: {e}")
        return False

    def get(self, key: str) -> bytes | None:
        if not self.ok:
            return None
        try:
            r = self.s.get(f"{self.base}/r2/buckets/{BUCKET}/objects/{key}", timeout=300)
            return r.content if r.ok else None
        except Exception as e:  # noqa: BLE001
            print(f"[store] R2 get {key}: {e}")
            return None

    def list_keys(self, prefix: str) -> list[str] | None:
        """Object keys under a prefix; None when the listing failed. Each page (up to 1,000 keys) is one Class A operation."""
        if not self.ok:
            return None
        keys, cursor = [], None
        try:
            for _ in range(100):
                params = {"prefix": prefix, "per_page": 1000, **({"cursor": cursor} if cursor else {})}
                r = self.s.get(f"{self.base}/r2/buckets/{BUCKET}/objects", params=params, timeout=60)
                js = r.json()
                if not r.ok or js.get("success") is False:
                    print(f"[store] R2 list {prefix}: http {r.status_code} {str(js.get('errors'))[:160]}")
                    return None
                res = js.get("result") or []
                if isinstance(res, dict):
                    res = res.get("objects") or []
                keys += [o["key"] for o in res if isinstance(o, dict) and o.get("key")]
                info = js.get("result_info") or {}
                cursor = info.get("cursor")
                if not info.get("is_truncated") or not cursor:
                    break
            return keys
        except Exception as e:  # noqa: BLE001
            print(f"[store] R2 list {prefix}: {e}")
            return None

    def delete(self, key: str) -> bool:
        """Delete one object (free on R2). A key that is already gone counts as deleted."""
        if not self.ok:
            return False
        try:
            r = self.s.delete(f"{self.base}/r2/buckets/{BUCKET}/objects/{key}", timeout=60)
            if r.ok or r.status_code == 404:
                self.r2_deletes += 1
                return True
            print(f"[store] R2 delete {key}: http {r.status_code} {r.text[:160]}")
        except Exception as e:  # noqa: BLE001
            print(f"[store] R2 delete {key}: {e}")
        return False

    def usage(self) -> dict:
        return {"d1_rows_written": self.rows_written, "d1_calls": self.calls, "d1_free_rows_per_day": 100_000,
                "r2_puts": self.r2_puts, "r2_mb": round(self.r2_bytes / 1e6, 1), "r2_deletes": self.r2_deletes,
                "r2_free_puts_per_month": 1_000_000}


def gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str).encode())
