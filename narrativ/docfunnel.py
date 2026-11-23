"""Document funnel D1: decide from the subject line alone whether a filing is worth downloading.

Rules live in data/doc_rules.json (editable). First match wins. No match -> 'download' with rule 'Unknown'.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "doc_rules.json"


@lru_cache(maxsize=1)
def rules() -> list[tuple[str, str, re.Pattern]]:
    raw = json.loads(RULES_FILE.read_text())["rules"]
    return [(g, n, re.compile(p, re.I)) for g, n, p in raw]


def classify(category: str | None, text: str | None) -> tuple[str, str]:
    """-> (group, rule). group in download | event | skip."""
    s = f"{category or ''} | {text or ''}"
    for g, n, rx in rules():
        if rx.search(s):
            return g, n
    return "download", "Unknown"
