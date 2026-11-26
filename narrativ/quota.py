"""Free Gemini API allowance guard for the reader (owner, 26 Nov 2026).

Limits are the Narrativ project's free tier as shown in AI Studio (aistudio.google.com/rate-limit, read 26 Nov 2026), set a
little under Google's numbers. Every call is counted per model per Pacific day (the free tier resets at midnight Pacific,
about 13:30 IST) in data/reader/usage.json. The story job (narrativ/story.py) does not write this count, and its 06:30 and
09:30 IST runs fall in the SAME Pacific day as the previous evening's reader (17:40 IST is ~04:10 Pacific; 06:30 IST next
day is ~17:00 Pacific, before the reset; audit 26 Nov 2026). So the reader leaves STORY_RESERVE calls of each story model
unused (reader_cap). A refused call (HTTP 429) is retried once after a minute; a second refusal in a row ends that model for
the day and the caller moves to the next model in its list (a successful call resets the count).
Pacing is by tokens as well as requests: at ~27k tokens a transcript, 250K tokens a minute allows ~9 documents a minute.
"""
import json
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

USAGE = Path("data/reader/usage.json")
PACIFIC = ZoneInfo("America/Los_Angeles")

# model id pattern -> (requests a minute, tokens a minute, requests a day we allow ourselves); Google's numbers in comments
LIMITS = [
    (r"^gemini-3\.5-flash-lite", 14, 240_000, 480),   # 15 / 250K / 500
    (r"^gemini-3\.1-flash-lite", 14, 240_000, 480),   # 15 / 250K / 500 (shared with the story job: reader_cap)
    (r"^gemini-2\.5-flash-lite", 9, 240_000, 19),     # 10 / 250K / 20
    (r"flash-lite", 9, 240_000, 19),                  # any other Flash-Lite alias: careful default
    (r"^gemma-4", 28, 15_000, 14_000),                # 30 / 16K / 14.4K (26B and 31B counted apart)
    (r".", 4, 240_000, 19),                           # Gemini 4 Hydrogen, 3.8 / 3.6 / 3 / 2.5 Flash: 5 / 250K / 20
]


# models the story job calls (narrativ/story.py MODELS), as patterns so a resolved id ("-preview", "-001") still matches
STORY_MODELS = [r"^gemini-3\.1-flash-lite", r"^gemma-4-31b", r"^gemma-4-26b", r"^gemini-flash-lite-latest"]
STORY_RESERVE = 250  # calls a day kept for the story job (up to 300 sheets a run, most sheets one call; backfill days use more)


def reader_cap(model: str) -> int | None:
    """The reader's own daily cap on a model: its allowance minus STORY_RESERVE for a story model; None for other models."""
    if any(re.search(p, model) for p in STORY_MODELS):
        return max(0, limits(model)[2] - STORY_RESERVE)
    return None


def limits(model: str) -> tuple[int, int, int]:
    for pat, rpm, tpm, rpd in LIMITS:
        if re.search(pat, model):
            return rpm, tpm, rpd
    return 4, 240_000, 19


def tokens(chars: int, out: int = 3000) -> int:
    """Rough token count of a request: ~4 characters a token in, plus the expected answer."""
    return chars // 4 + out


class Quota:
    def __init__(self, path: Path = USAGE):
        self.path, self.lock = path, threading.Lock()
        self.win: dict[str, deque] = {}
        self.refusals: dict[str, int] = {}
        self.out: set = set()
        try:
            self.data = json.loads(path.read_text()) if path.exists() else {}
        except ValueError:
            self.data = {}

    def day(self) -> dict:
        d = str(datetime.now(PACIFIC).date())
        for k in [k for k in self.data if k < d][:-6]:  # keep a week
            self.data.pop(k, None)
        return self.data.setdefault(d, {})

    def used(self, model: str) -> int:
        with self.lock:
            return (self.day().get(model) or {}).get("calls", 0)

    def left(self, model: str) -> int:
        return 0 if model in self.out else max(0, limits(model)[2] - self.used(model))

    def take(self, model: str, est_tokens: int, stop_at: float | None = None, cap: int | None = None) -> bool:
        """Wait until a call fits this minute's requests and tokens, then count it. False: the day's allowance is used (or the
        model was refused twice), or the wait would pass stop_at."""
        rpm, tpm, rpd = limits(model)
        rpd = min(rpd, cap) if cap is not None else rpd
        est = min(est_tokens, tpm)
        while True:
            with self.lock:
                if model in self.out:
                    return False
                rec = self.day().setdefault(model, {"calls": 0, "refused": 0, "tokens": 0})
                if rec["calls"] >= rpd:
                    self.out.add(model)
                    return False
                w = self.win.setdefault(model, deque())
                now = time.time()
                while w and now - w[0][0] > 60:
                    w.popleft()
                if len(w) < rpm and sum(t for _, t in w) + est <= tpm:
                    w.append((now, est))
                    rec["calls"] += 1
                    rec["tokens"] += est
                    self._save()
                    return True
                wait = max(1.0, 60 - (now - w[0][0]) + 0.5)
            if stop_at and time.time() + wait > stop_at:
                return False
            time.sleep(wait)

    def count(self, model: str, est_tokens: int = 0, refused: bool = False) -> None:
        """Count a call made outside take() (the story job): accounting only, nothing is held back (cost audit 26 Nov 2026)."""
        with self.lock:
            rec = self.day().setdefault(model, {"calls": 0, "refused": 0, "tokens": 0})
            rec["refused" if refused else "calls"] += 1
            rec["tokens"] += 0 if refused else est_tokens
            rec["story"] = rec.get("story", 0) + 1
            self._save()

    def ok(self, model: str) -> None:
        """A call that was not refused: the next 429 is a first refusal again (audit 26 Nov 2026)."""
        with self.lock:
            self.refusals[model] = 0

    def refused(self, model: str) -> bool:
        """Record a 429. True: wait a minute and try once more; False: two in a row, the model is done for today."""
        with self.lock:
            rec = self.day().setdefault(model, {"calls": 0, "refused": 0, "tokens": 0})
            rec["refused"] += 1
            self.refusals[model] = self.refusals.get(model, 0) + 1
            if self.refusals[model] >= 2:
                self.out.add(model)
            self._save()
            return model not in self.out

    def gone(self, model: str) -> None:
        """A model the key cannot use (HTTP 404) or that errors repeatedly: skip it for this run."""
        with self.lock:
            self.out.add(model)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True))


def resolve(wanted: list[str], available: list[str]) -> list[str]:
    """Model ids for a lane, in order: each wanted pattern matched against the key's model list (first match, preferring a
    stable id over -preview / -exp). Text models only."""
    skip = re.compile(r"tts|image|live|audio|embedding|robotics|transcribe|computer", re.I)
    out = []
    for pat in wanted:
        hits = [m for m in available if re.search(pat, m) and not skip.search(m) and m not in out]
        hits.sort(key=lambda m: (("preview" in m) or ("exp" in m), len(m)))
        if hits:
            out.append(hits[0])
    return out
