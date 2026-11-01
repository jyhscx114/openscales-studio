"""Extract candidate user-interface strings from the shell sources.

Scale *content* lives in data/ and is translated separately; this harvests only
the shell: index.html text nodes, and string literals in app.js / scale-runner.js
that read as natural language rather than markup, class names or code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HTML_TEXT = re.compile(r">([^<>{}\n]*[A-Za-z][^<>{}]*[A-Za-z][^<>{}]*)<")
HTML_ATTR = re.compile(r'(placeholder|aria-label|title|alt)="([^"]*[A-Za-z][^"]*)"')
JS_STR = re.compile(r"'((?:[^'\\]|\\.)*)'")
JS_TSTR = re.compile(r'"((?:[^"\\]|\\.)*)"')

# Things that look like words but are UI chrome, code, or data — never translate.
SKIP = re.compile(
    r"^(?:[a-z-]+(?:\s+[a-z-]+)*|#[0-9a-fA-F]+|\d+(?:px|rem|em|%)?)$"
)
NOT_NATURAL = re.compile(
    r"(?:^\s*$|^\s*[a-z0-9_-]+\s*$"          # single token / kebab-case
    r"|\.js$|\.css$|\.json$|\.osd$|\.html$"  # filenames
    r"|^https?://|^\w+://"                    # urls
    r"|^[a-z-]+$|^os-|^sr-|^#/"               # class names / routes
    r"|^[A-Z_]{2,}$)"                         # constants
)


def looks_natural(text: str) -> bool:
    t = text.strip()
    if len(t) < 2 or len(t) > 120:
        return False
    if NOT_NATURAL.search(t):
        return False
    if not re.search(r"[A-Za-z]", t):
        return False
    # Out of a sample of letters, real sentences have spaces or a capital start.
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", t)
    if len(words) < 1:
        return False
    return True


def main() -> None:
    out: dict[str, dict] = {}

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for m in HTML_TEXT.finditer(html):
        t = m.group(1).strip()
        if looks_natural(t):
            out.setdefault(t, {"kind": "html-text", "file": "index.html"})
    for m in HTML_ATTR.finditer(html):
        t = m.group(2).strip()
        if looks_natural(t):
            out.setdefault(t, {"kind": "html-attr", "file": "index.html"})

    for name in ("assets/app.js", "assets/scale-runner.js"):
        src = (ROOT / name).read_text(encoding="utf-8")
        for rx in (JS_STR, JS_TSTR):
            for m in rx.finditer(src):
                raw = m.group(1)
                if "\\n" in raw or "\\t" in raw:
                    continue
                t = raw.replace("\\'", "'").strip()
                if looks_natural(t):
                    out.setdefault(t, {"kind": "js-literal", "file": name})

    # Sensible English sentences only: drop things carrying template noise.
    cleaned = {}
    for text, meta in out.items():
        if re.search(r"[{}<>]{2,}|\$\{|&=\w|==", text):
            continue
        if re.search(r";|\(\)|=\s*$", text):
            continue
        cleaned[text] = meta

    target = ROOT / "tools" / "ui-strings.json"
    target.write_text(json.dumps(
        {t: {"zh": "", "kind": m["kind"], "file": m["file"]}
         for t, m in sorted(cleaned.items())},
        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    kinds: dict[str, int] = {}
    for meta in cleaned.values():
        kinds[meta["kind"]] = kinds.get(meta["kind"], 0) + 1
    print(f"extracted {len(cleaned)} candidate strings -> {target}")
    print("by kind:", kinds)


if __name__ == "__main__":
    main()
