#!/usr/bin/env python3
"""
inject_zh.py — Fold the translated corpus into an already-built data bundle.

Normally ``build_data.py`` does this while packaging from an OpenScales
checkout. When no checkout is reachable (offline box, air-gapped deploy) you can
instead re-key the shipped ``data/scales/*.js`` files in place: the translation
corpus lives inside this repository, so no network is needed either way.

Usage
-----
    python3 tools/inject_zh.py                 # every scale in data/scales
    python3 tools/inject_zh.py --map-only      # just report corpus coverage

Re-running is safe: the ``zh`` block is rebuilt from scratch each time, and
``manifest.js`` is updated to list the language wherever it was added.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import zhpack

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCALES = ROOT / "data" / "scales"
MANIFEST = ROOT / "data" / "manifest.js"

# (window.OS_SCALES=window.OS_SCALES||{})["CODE"]={ ... };
HEAD_RE = re.compile(
    r'^\(window\.OS_SCALES=window\.OS_SCALES\|\|\{\}\)\["(?P<code>[^"]+)"\]='
)


def read_bundle(path: Path):
    text = path.read_text(encoding="utf-8")
    m = HEAD_RE.match(text)
    if not m:
        return None, None
    body = text[m.end():].rstrip()
    if body.endswith(";"):
        body = body[:-1]
    return m.group("code"), json.loads(body)


def write_bundle(path: Path, code: str, bundle) -> int:
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    line = ('(window.OS_SCALES=window.OS_SCALES||{})["' + code + '"]=' + payload + ";\n")
    path.write_text(line, encoding="utf-8")
    return len(line.encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map-only", action="store_true",
                    help="Report corpus size and exit without touching data.")
    ap.add_argument("--limit", type=int, default=0, help="Only process the first N files.")
    args = ap.parse_args()

    zh_map = zhpack.load_map()
    if not zh_map:
        print("No Chinese corpus found. Run tools/translate.py first.", file=sys.stderr)
        return 1
    print(f"Chinese corpus: {len(zh_map):,} translated strings")

    if args.map_only:
        return 0

    files = sorted(SCALES.glob("*.js"))
    if args.limit:
        files = files[: args.limit]

    done = 0
    keys = 0
    skipped = 0
    for i, path in enumerate(files, 1):
        code, bundle = read_bundle(path)
        if bundle is None:
            skipped += 1
            continue
        translations = bundle.get("translations")
        n = zhpack.add_chinese(translations or {}, zh_map)
        if n:
            bundle["translations"] = translations
            write_bundle(path, code, bundle)
            done += 1
            keys += n
        if i % 200 == 0:
            print(f"  {i}/{len(files)}")

    print(f"folded zh into {done} bundles ({keys:,} keys), skipped {skipped}")

    if done:
        patch_manifest()
    return 0


def patch_manifest() -> None:
    """Ensure the global language list contains zh and re-emit the file."""
    raw = MANIFEST.read_text(encoding="utf-8")
    prefix, _, rest = raw.partition("=")
    body = rest.strip()
    if body.endswith(";"):
        body = body[:-1]
    data = json.loads(body)

    langs = data.get("languages") or []
    if isinstance(langs, list) and "zh" not in langs:
        langs.append("zh")
        langs.sort()
        data["languages"] = langs

    MANIFEST.write_text(prefix + "=" + json.dumps(data, ensure_ascii=False,
                                                  separators=(",", ":")) + ";\n",
                        encoding="utf-8")
    print(f"manifest.js updated — {len(langs)} languages listed")


if __name__ == "__main__":
    sys.exit(main())
