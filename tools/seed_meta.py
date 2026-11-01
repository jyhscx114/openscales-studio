#!/usr/bin/env python3
"""
seed_meta.py — Queue the human-facing *metadata* for translation.

The item corpus (what a participant reads) is translated from the bundles. The
browsing chrome needs Chinese too, and those strings live in the manifest
rather than in a translation block:

  - domain       97 distinct values, used by the filter dropdown and every card chip
  - name         the scale title shown on cards, detail heading and result card
  - description  the blurb under a card title

Everything lands in the same ``jobs`` table ``tools/translate.py`` already
consumes, so dedup against the existing corpus is automatic and only genuinely
new strings cost tokens.

Usage
-----
    python3 tools/seed_meta.py          # queue anything not seen before
    python3 tools/translate.py          # run the same worker pipeline
    python3 tools/build_data.py --source <checkout>   # fold in as *_zh fields
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = ROOT / "data" / "manifest.js"
DB = ROOT / "data" / "translate.sqlite3"


def load_manifest() -> list[dict]:
    raw = MANIFEST.read_text(encoding="utf-8")
    for part in re.split(r"(?=window\.\w+=)", raw):
        if not part.strip():
            continue
        name, _, rest = part.partition("=")
        if name.strip() == "window.OS_MANIFEST":
            return json.loads(rest.rstrip().rstrip(";"))
    raise SystemExit("manifest.js has no OS_MANIFEST assignment")


def main() -> int:
    rows = load_manifest()

    wanted: list[str] = []
    seen: set[str] = set()

    def add(value: str):
        if not isinstance(value, str):
            return
        text = re.sub(r"\s+", " ", value).strip()
        if not text or text in seen:
            return
        seen.add(text)
        wanted.append(text)

    for m in rows:
        add(m.get("domain"))
    for m in rows:
        add(m.get("name"))
    for m in rows:
        add(m.get("description"))

    conn = sqlite3.connect(str(DB))
    q = lambda sql: conn.execute(sql).fetchone()[0]

    before = q("SELECT COUNT(*) FROM jobs")
    conn.executemany(
        "INSERT OR IGNORE INTO jobs (src, chars, status) VALUES (?, ?, 'pending')",
        [(s, len(s)) for s in wanted],
    )
    conn.commit()

    q = lambda sql: conn.execute(sql).fetchone()[0]
    added = q("SELECT COUNT(*) FROM jobs") - before
    pending = q("SELECT COUNT(*) FROM jobs WHERE status='pending'")
    done = q("SELECT COUNT(*) FROM jobs WHERE status='done'")
    chars = q("SELECT COALESCE(SUM(chars),0) FROM jobs WHERE status='pending'")

    print(f"metadata strings found | {len(wanted):,}")
    print(f"newly queued           | {added:,} (rest already translated or known)")
    print(f"pending now            | {pending:,} strings / {chars:,} chars")
    print(f"already translated     | {done:,}")
    print("\nNext: python3 tools/translate.py  (then rebuild with build_data.py)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
