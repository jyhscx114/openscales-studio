#!/usr/bin/env python3
"""
translate.py — batch-translate every English string in the bundles to Chinese.

Runs against the iFlytek MaaS endpoint with thinking disabled (5x cheaper,
~3x faster) and SQLite as the store, so it stops and resumes safely and every
unique string is paid for exactly once.

    export IFLYTEK_API_KEY=...
    python3 tools/translate.py --limit 300      # smoke test
    python3 tools/translate.py --workers 12     # the whole corpus
    python3 tools/translate.py --retry-failed   # clean up stragglers

Translations are written into data/translate.sqlite3; tools/build_data.py then
folds them back into the bundles as a `zh` language.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

URL = "https://maas-api.cn-huabei-1.xf-yun.com/v2/chat/completions"
MODEL = "spark-x2.6"
DB = Path(__file__).resolve().parent.parent / "data" / "translate.sqlite3"

# Batching sweet spot: prompt stays small enough that 30 replies fit comfortably
# inside the completion window, while per-request overhead stays amortised.
MAX_ITEMS = 28
MAX_CHARS = 900

PROMPT = (
    "You are localising a psychological assessment instrument into Simplified "
    "Chinese.\n"
    "Translate ONLY the text after the pipe in each numbered line.\n"
    "Rules:\n"
    "- Be precise and literal; this scores patients, so never soften, never "
    "expand, never explain.\n"
    "- Keep clinical terms correct (panic -> 惊恐, anhedonia -> 快感缺失, "
    "Likert -> 李克特, burnout -> 倦怠).\n"
    "- Keep any placeholder or markup (e.g. {name}, %%p%%, <b>x</b>) intact.\n"
    "- Translate even single words: Yes -> 是, No -> 否, True -> 真, "
    "False -> 假, Male -> 男, Female -> 女, Other -> 其他.\n"
    "- Never leave a line untranslated, and never echo the English.\n\n"
    "__ITEMS__\n\n"
    'Reply with JSON ONLY, exactly this shape: '
    '{{"1":"translation of line 1","2":"translation of line 2"}}\n'
)

_lock = threading.Lock()
_stats = {"done": 0, "failed": 0, "chars": 0, "reqs": 0, "started": time.time()}


def api_key() -> str:
    key = os.environ.get("IFLYTEK_API_KEY") or os.environ.get("IFLYTEK_KEY") or ""
    if not key:
        sys.exit("Set IFLYTEK_API_KEY first.")
    return key


def ask(texts: list[str], key: str, tries: int = 3) -> list[str] | None:
    """Translate one batch; returns a list aligned to `texts`, or None."""
    # replace(), not format(): the strings contain braces of their own
    # (placeholders like {name}) that would otherwise be read as templates.
    body = "\n".join(f"{i+1}|{t}" for i, t in enumerate(texts))
    content = PROMPT.replace("__ITEMS__", body)
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
        "enable_thinking": False,   # cuts completion tokens ~5x
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}

    for attempt in range(tries):
        try:
            resp = requests.post(URL, headers=headers, json=payload, timeout=180)
            if resp.status_code != 200:
                time.sleep(1.5 * (attempt + 1))
                continue
            raw = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            # Network hiccup: back off. Anything else is a bug and should be
            # loud rather than silently turning the whole batch into failures.
            if "HTTP" not in str(exc)[:8]:
                print(f"  ! unexpected: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            time.sleep(1.5 * (attempt + 1))
            continue

        parsed = parse_json(raw, len(texts))
        if parsed is not None:
            with _lock:
                _stats["reqs"] += 1
            return [str(parsed[str(i + 1)]).strip() for i in range(len(texts))]
        if len(texts) == 1:
            # Last resort for a stubborn single line.
            flat = strip_to_translation(raw, texts[0])
            if flat:
                return [flat]
    return None


def parse_json(raw: str, expect: int) -> dict | None:
    """Extract the numbered map even if the model fenced, padded or relabelled it."""
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        for candidate in (text[start:end + 1],):
            try:
                obj = json.loads(candidate)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                # Keys sometimes come back as "1|original"; normalise to "1".
                clean = {}
                for k, v in obj.items():
                    m = re.match(r"\s*(\d+)", str(k))
                    if m and isinstance(v, str) and v.strip():
                        clean[m.group(1)] = v.strip()
                if len(clean) == expect:
                    return clean

    # Fall back to "1|translation" line format.
    lines = {}
    for m in re.finditer(r"^\s*(\d+)\s*[|｜.、:：]\s*(.+?)\s*$", text, re.M):
        idx, val = m.group(1), m.group(2)
        if val.startswith("|"):
            continue
        lines[idx] = val
    return lines if len(lines) == expect else None


def strip_to_translation(raw: str, source: str) -> str | None:
    """Salvage a single line of text from a chatty reply."""
    text = raw.strip().strip('"').strip()
    if not text or len(text) > max(400, len(source) * 4):
        return None
    if "\n" in text or text.lower().startswith(("json", "here", "the translation")):
        return None
    return text


def batch(items: list[tuple[str, int]]) -> list[list[tuple[str, int]]]:
    """Group pending strings into batches bounded by both count and size."""
    out, cur, size = [], [], 0
    for src, chars in items:
        # Very long passages travel alone so the reply never truncates.
        if chars > 600:
            if cur:
                out.append(cur)
                cur, size = [], 0
            out.append([(src, chars)])
            continue
        if len(cur) >= MAX_ITEMS or size + chars > MAX_CHARS:
            if cur:
                out.append(cur)
            cur, size = [], 0
        cur.append((src, chars))
        size += chars
    if cur:
        out.append(cur)
    return out


def save(con, results: dict[str, str]):
    with _lock:
        con.executemany(
            "UPDATE jobs SET status='done', dst=? WHERE src=?",
            [(v, k) for k, v in results.items()],
        )
        con.commit()


def mark_failed(con, srcs: list[str]):
    with _lock:
        con.executemany(
            "UPDATE jobs SET status='failed', tries=tries+1 WHERE src=?",
            [(s,) for s in srcs],
        )
        con.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only translate this many strings")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--order", choices=["short", "any"], default="short")
    args = ap.parse_args()

    key = api_key()
    if not DB.exists():
        sys.exit(f"Missing {DB}. Run the extraction step described in README.md first.")
    con = sqlite3.connect(DB, check_same_thread=False)

    order = "ORDER BY chars" if args.order == "short" else ""
    if args.retry_failed:
        rows = con.execute(
            f"SELECT src, chars FROM jobs WHERE status='failed' {order} LIMIT ?",
            (args.limit or 10 ** 9,),
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT src, chars FROM jobs WHERE status='pending' {order} LIMIT ?",
            (args.limit or 10 ** 9,),
        ).fetchall()

    if not rows:
        print("Nothing pending.")
        pending = con.execute("SELECT COUNT(*) FROM jobs WHERE status='pending'").fetchone()[0]
        done = con.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
        print(f"  done={done} pending={pending}")
        return 0

    batches = batch(rows)
    print(f"queueing {len(rows)} strings in {len(batches)} requests with {args.workers} workers")

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for group in batches:
            if args.limit and sum(len(g) for g in futures.values()) >= args.limit:
                break
            futures[pool.submit(ask, [g[0] for g in group], key)] = group

        done_one = False
        for fut in as_completed(futures):
            group = futures[fut]
            try:
                result = fut.result()
            except Exception:
                result = None
            if result:
                save(con, dict(zip([g[0] for g in group], result)))
                _stats["done"] += len(group)
                _stats["chars"] += sum(len(r) for r in result)
            else:
                mark_failed(con, [g[0] for g in group])
                _stats["failed"] += len(group)
            completed += len(group)
            _stats.setdefault("processed", 0)
            _stats["processed"] = _stats.get("processed", 0) + len(group)
            n = _stats.get("processed", 0)
            if n % 500 < len(group) or not done_one:
                done_one = True
                el = time.time() - _stats["started"]
                rate = n / el if el else 0
                print(f"  {n:6}/{len(rows)}  {rate:5.1f} str/s  "
                      f"ok={_stats['done']} fail={_stats['failed']}  {el/60:.1f} min", flush=True)

    el = time.time() - _stats["started"]
    print(f"\nfinished {_stats['done']} strings in {_stats['reqs']} requests, "
          f"{el/60:.1f} min. failures: {_stats['failed']}")
    if _stats["failed"]:
        print("re-run with --retry-failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
