"""App files -> R2, so the Worker (worker/worker.js) serves /data/<path> from R2 key app/<path> instead of the GitHub API.

    python -m narrativ.appsync          # after a successful `git push` (scripts/push_retry.sh, reader.save); never fatal
    python -m narrativ.appsync --full   # re-upload every file (repair after objects were removed by hand)

Order: run only AFTER the commit is on GitHub's main, so R2 never runs ahead of git. Content comes from the pushed commit
(HEAD's tree via `git cat-file`), not the work tree, so uncommitted local edits never reach the app.

What is uploaded: every docs/data/**.json whose git blob id differs from the one recorded in R2 `app/_manifest.json`
(the manifest is the hash index, like dbsync's; the blob id IS the content hash). Files gone from HEAD are deleted. The
diff is against what R2 holds, not against what this job changed, so any job's run also catches up files that other jobs
(or a failed upload) left behind.

`app/_manifest.json` = {"v": 1, "sha": commit, "ct": commit time, "at": upload time, "failed": [paths], "blobs": {path:
blob}}. Invariant: for every path NOT in `failed`, R2 holds that path's content at commit `sha` (or nothing when the path
does not exist at `sha`). The Worker trusts R2 only for paths that did not change between `sha` and main (one GitHub
compare call, at most once a minute per isolate) and are not in `failed`; everything else is read from GitHub as before.

A run (1) claims: rewrites the manifest with every path it is about to change in `failed` and blob "?"; (2) uploads and
deletes; (3) writes the final manifest. A run that dies midway leaves its paths flagged (served from GitHub, re-uploaded
next time). Manifest writes are conditional (If-Match the copy read last); when another uploader wrote meanwhile (e.g.
reader and republish at once) the two are merged: the older commit, both failure lists, "?" where they disagree.

Transport: R2's S3 endpoint (SigV4), not the REST API (api.cloudflare.com allows 1,200 requests per 5 minutes per user and
D1 shares that limit; a daily run changes ~6,000 files). S3 keys: R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY when set, else
derived from CLOUDFLARE_API_TOKEN as Cloudflare documents (access key id = the token's id, secret = SHA-256 of the token).

Class A budget (R2 free: 1M a month): one PUT per changed file plus two manifest PUTs per run; deletes are free.
Estimate: daily run ~6,000 changed files x ~22 trading days = ~132k, republish / reader / small jobs ~5k: ~140k a month.
"""
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

BUCKET = "narrativ-data"
SRC = "docs/data"            # uploaded tree; the Worker maps /data/<path> -> docs/<path> -> R2 app/<path>
KEY_PREFIX = "app/"
MANIFEST_KEY = "app/_manifest.json"
PATH_OK = re.compile(r"^[\w\-./&]+\.json$")  # the Worker's /data path whitelist
WORKERS = max(1, int(os.environ.get("R2_APP_WORKERS", "16")))
CF_API = "https://api.cloudflare.com/client/v4"


# ---------------------------------------------------------------- HTTP (requests when installed, else urllib)
def _http_default():
    """call(method, url, headers, data, timeout) -> (status, {lower-case header: value}, body)."""
    try:
        import requests
        from requests.adapters import HTTPAdapter
    except ImportError:
        import urllib.error
        import urllib.request

        def call(method, url, headers=None, data=None, timeout=60):
            req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
            except urllib.error.HTTPError as e:
                return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""
        return call
    s = requests.Session()
    s.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=WORKERS + 4, max_retries=0))

    def call(method, url, headers=None, data=None, timeout=60):
        r = s.request(method, url, headers=headers or {}, data=data, timeout=timeout)
        return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content
    return call


class R2S3:
    """Minimal S3 client for one R2 bucket: get / put (with If-Match / If-None-Match) / delete, AWS SigV4 signed."""

    def __init__(self, account: str, key_id: str, secret: str, bucket: str = BUCKET, http=None):
        self.host = f"{account}.r2.cloudflarestorage.com"
        self.bucket, self.key_id, self.secret = bucket, key_id, secret
        self.http = http or _http_default()

    @classmethod
    def from_env(cls, http=None) -> "R2S3 | None":
        acc = "".join(os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").split()).strip("\"'")
        if not acc:
            return None
        http = http or _http_default()
        kid, sec = os.environ.get("R2_ACCESS_KEY_ID", "").strip(), os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
        if kid and sec:
            return cls(acc, kid, sec, http=http)
        tok = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        if not tok:
            return None
        for url in (f"{CF_API}/user/tokens/verify", f"{CF_API}/accounts/{acc}/tokens/verify"):
            try:
                st, _, body = http("GET", url, {"Authorization": f"Bearer {tok}"}, None, 30)
                tid = ((json.loads(body or b"{}").get("result") or {}).get("id") or "") if st == 200 else ""
            except Exception:  # noqa: BLE001
                tid = ""
            if tid:
                return cls(acc, tid, hashlib.sha256(tok.encode()).hexdigest(), http=http)
        print("[appsync] could not read the API token's id (tokens/verify); set R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY")
        return None

    def _req(self, method: str, key: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 60):
        uri = "/" + self.bucket + "/" + quote(key, safe="/")
        now = time.gmtime()
        amz, day = time.strftime("%Y%m%dT%H%M%SZ", now), time.strftime("%Y%m%d", now)
        ph = hashlib.sha256(data or b"").hexdigest()
        signed = {"host": self.host, "x-amz-content-sha256": ph, "x-amz-date": amz}
        names = ";".join(sorted(signed))
        canon = "\n".join([method, uri, "", "".join(f"{k}:{signed[k]}\n" for k in sorted(signed)), names, ph])
        scope = f"{day}/auto/s3/aws4_request"
        sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canon.encode()).hexdigest()])
        k = ("AWS4" + self.secret).encode()
        for part in (day, "auto", "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
        h = {"x-amz-content-sha256": ph, "x-amz-date": amz,
             "Authorization": f"AWS4-HMAC-SHA256 Credential={self.key_id}/{scope}, SignedHeaders={names}, Signature={sig}",
             **(headers or {})}
        return self.http(method, f"https://{self.host}{uri}", h, data, timeout)

    def get(self, key: str) -> tuple[int, bytes, str | None]:
        st, h, body = self._req("GET", key)
        return st, body, h.get("etag")

    def put(self, key: str, data: bytes, ctype: str = "application/json; charset=utf-8", if_match: str | None = None,
            if_none_match: str | None = None) -> tuple[int, str | None]:
        h = {"Content-Type": ctype}
        if if_match:
            h["If-Match"] = if_match
        if if_none_match:
            h["If-None-Match"] = if_none_match
        st, rh, _ = self._req("PUT", key, data, h, 120)
        return st, rh.get("etag")

    def delete(self, key: str) -> int:
        return self._req("DELETE", key)[0]


# ---------------------------------------------------------------- git
def _git(*a: str, inp: bytes | None = None) -> bytes:
    return subprocess.run(["git", *a], input=inp, capture_output=True, check=True).stdout


def head_tree(rev: str = "HEAD") -> dict[str, str]:
    """{path under docs/ (as the app asks for it): blob id} of every servable docs/data/**.json in `rev`."""
    out = {}
    for rec in _git("ls-tree", "-r", "-z", "--full-tree", rev, "--", SRC).split(b"\0"):
        if not rec:
            continue
        meta, path = rec.decode("utf-8", "surrogateescape").split("\t", 1)
        _mode, typ, blob = meta.split()
        rel = path[len("docs/"):]
        if typ == "blob" and PATH_OK.match(rel) and not any(s in ("", ".", "..") for s in rel.split("/")):
            out[rel] = blob
    return out


def read_blobs(blobs: list[str]) -> dict[str, bytes]:
    """Contents of many blobs in one `git cat-file --batch` call."""
    if not blobs:
        return {}
    raw = _git("cat-file", "--batch", inp=("\n".join(blobs) + "\n").encode())
    out, i = {}, 0
    while i < len(raw):
        nl = raw.index(b"\n", i)
        head = raw[i:nl].split()
        if len(head) < 3:  # "<id> missing"
            i = nl + 1
            continue
        size = int(head[2])
        out[head[0].decode()] = raw[nl + 1: nl + 1 + size]
        i = nl + 1 + size + 1
    return out


def head_commit() -> tuple[str, int]:
    sha, ct = _git("log", "-1", "--format=%H %ct", "HEAD").decode().split()
    return sha, int(ct)


# ---------------------------------------------------------------- sync
def _load_manifest(r2: R2S3) -> tuple[dict | None, str | None]:
    """(manifest, its etag). Missing: ({}, None). Unreadable bucket: (None, None)."""
    st, body, etag = r2.get(MANIFEST_KEY)
    if st == 404:
        return {}, None
    if st != 200:
        print(f"[appsync] manifest read: http {st}")
        return None, None
    try:
        m = json.loads(body)
        return (m if isinstance(m, dict) and m.get("v") == 1 else {}), etag
    except ValueError:
        return {}, etag


def merge_conflict(ours: dict, theirs: dict) -> dict:
    """Manifest to write when another uploader wrote while this one ran: the older commit, the union of both failure lists,
    and "?" (plus a failure entry) for every path whose blob the two disagree on: its R2 content is whichever upload landed
    last, so the Worker reads it from GitHub and the next run uploads it again."""
    older = ours if not theirs.get("sha") or int(ours.get("ct") or 0) <= int(theirs.get("ct") or 0) else theirs
    a, b = ours.get("blobs") or {}, theirs.get("blobs") or {}
    blobs = {p: (a.get(p) if a.get(p) == b.get(p) else "?") for p in set(a) | set(b)}
    failed = set(ours.get("failed") or []) | set(theirs.get("failed") or []) | {p for p, v in blobs.items() if v == "?"}
    return {"v": 1, "sha": older.get("sha"), "ct": older.get("ct"), "at": ours.get("at"), "failed": sorted(failed), "blobs": blobs}


def _write_manifest(r2: R2S3, man: dict, etag: str | None, res: dict) -> str | None:
    """Conditional write (If-Match the copy last read, or If-None-Match * when there was none). On a conflict the other
    writer's copy is merged in (merge_conflict) and the write retried. Returns the new ETag ("" when R2 sent none), or None
    when not written."""
    for _ in range(5):
        body = json.dumps(man, sort_keys=True, separators=(",", ":")).encode()
        st, new = r2.put(MANIFEST_KEY, body, if_match=etag) if etag else r2.put(MANIFEST_KEY, body, if_none_match="*")
        res["puts"] += 1
        if 200 <= st < 300:
            return new or ""
        if st != 412:
            print(f"[appsync] manifest write: http {st}")
            return None
        theirs, etag = _load_manifest(r2)
        if theirs is None:
            return None
        print(f"[appsync] another upload wrote the manifest meanwhile (commit {str(theirs.get('sha'))[:8]}); merging")
        man = merge_conflict(man, theirs)
    return None


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(full: bool = False, r2: R2S3 | None = None) -> dict:
    """Upload what changed since the manifest; never raises. `puts` in the result = Class A operations used."""
    t0 = time.time()
    res = {"ok": False, "puts": 0, "uploaded": 0, "deletes": 0, "failed": 0, "unchanged": 0}
    try:
        r2 = r2 or R2S3.from_env()
        if r2 is None:
            print("[appsync] no Cloudflare credentials; skipped")
            return res
        old, etag = _load_manifest(r2)
        if old is None:
            return res
        sha, ct = head_commit()
        if not full and old.get("sha") and int(old.get("ct") or 0) > ct:  # a newer commit's upload already landed
            print(f"[appsync] {sha[:8]}: R2 holds a newer commit ({str(old['sha'])[:8]}); skipped")
            res["ok"], res["sha"] = True, old.get("sha")
            return res
        tree = head_tree()
        prev = dict(old.get("blobs") or {})
        todo = [p for p, b in tree.items() if full or prev.get(p) != b]
        gone = [p for p in prev if p not in tree]
        res["unchanged"] = len(tree) - len(todo)
        if not todo and not gone and not old.get("failed") and old.get("sha") and int(old.get("ct") or 0) >= ct:
            print(f"[appsync] {sha[:8]}: R2 already current ({len(tree)} files)")
            res["ok"], res["sha"] = True, old.get("sha")
            return res
        if todo or gone:  # (1) claim
            claim = {**old, "v": 1, "failed": sorted(set(old.get("failed") or []) | set(todo) | set(gone)),
                     "blobs": {**prev, **{p: "?" for p in todo + gone}}}
            new = _write_manifest(r2, claim, etag, res)
            if new is None:
                print("[appsync] could not claim the manifest; nothing uploaded")
                return res
            etag = new or _load_manifest(r2)[1]  # no ETag in the reply: read it back so the final write stays conditional
        data = read_blobs(sorted({tree[p] for p in todo}))

        def up(p: str) -> bool:
            body = data.get(tree[p])
            if body is None:
                return False
            for i in range(3):
                try:
                    st = r2.put(KEY_PREFIX + p, body)[0]
                    if 200 <= st < 300:
                        return True
                    if st not in (429, 500, 502, 503, 504):
                        print(f"[appsync] put {p}: http {st}")
                        return False
                except Exception as e:  # noqa: BLE001
                    if i == 2:
                        print(f"[appsync] put {p}: {e}")
                time.sleep(1 + 2 * i)
            return False

        def rm(p: str) -> bool:
            try:
                return r2.delete(KEY_PREFIX + p) in (200, 204, 404)
            except Exception as e:  # noqa: BLE001
                print(f"[appsync] delete {p}: {e}")
                return False

        with ThreadPoolExecutor(WORKERS) as pool:  # (2)
            put_ok = dict(zip(todo, pool.map(up, todo)))
            del_ok = dict(zip(gone, pool.map(rm, gone)))
        res["uploaded"], res["deletes"] = sum(put_ok.values()), sum(del_ok.values())
        res["puts"] += res["uploaded"]
        blobs = {p: b for p, b in prev.items() if p in tree or not del_ok.get(p)}
        blobs.update({p: tree[p] if put_ok[p] else "?" for p in todo})  # a failed put may or may not have landed
        failed = sorted([p for p in todo if not put_ok[p]] + [p for p in gone if not del_ok[p]])
        res["failed"] = len(failed)
        man = {"v": 1, "sha": sha, "ct": ct, "at": _now(), "failed": failed, "blobs": blobs}
        written = _write_manifest(r2, man, etag, res) is not None  # (3)
        res["ok"], res["sha"] = written, sha
        print(f"[appsync] {sha[:8]}: {res['uploaded']} uploaded, {res['deletes']} deleted, {res['unchanged']} unchanged, "
              f"{len(failed)} failed; manifest {'written' if written else 'NOT written (changed files stay on GitHub)'}; "
              f"{res['puts']} Class A ops ({time.time() - t0:.0f}s)")
    except Exception as e:  # noqa: BLE001
        print(f"[appsync] failed: {type(e).__name__}: {str(e)[:200]}")
    return res


if __name__ == "__main__":
    sync(full="--full" in sys.argv)
    sys.exit(0)  # never fails the calling step
