"""Fold the machine-translated corpus into each bundle as a Simplified Chinese
language block.

The corpus lives in ``data/translate.sqlite3`` (written by ``tools/translate.py``)
as English string -> Chinese string. This module applies it at build time.

Merge policy for the new ``zh`` block, in order:

1. Start from the bundle's English strings, translated through the corpus.
   Keyed messages the corpus never saw (or failed on) keep their English text —
   never a raw ``SOME_KEY`` leaking into the UI.
2. Human-authored Simplified Chinese already in the bundle wins outright.
   Only eight bundles ship one, and it beats a machine guess.
3. Keys that exist in some other language but not in English still get a
   translated entry, so switching language never renders a bare key.

Traditional variants (``zh-TW``, ``zh-HK``, ``zh-Hant``) are left alone and are
not used as a source — folding them in would quietly convert Traditional text
to Simplified.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Dict, Optional

DB = Path(__file__).resolve().parent.parent / "data" / "translate.sqlite3"

SIMPLIFIED = ("zh", "zh-CN", "zh-cn", "zh-Hans", "zh-hans", "zh_CN", "zh-Hans-CN")
TRADITIONAL = ("zh-TW", "zh-tw", "zh-HK", "zh-hk", "zh-Hant", "zh-hant")


def load_map(db_path: Optional[Path] = None) -> Dict[str, str]:
    """English -> Chinese, skipping anything that did not actually translate."""
    path = Path(db_path) if db_path else DB
    if not path.exists():
        return {}
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT src, dst FROM jobs WHERE status='done' AND dst IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    out: Dict[str, str] = {}
    for src, dst in rows:
        if not src or not dst:
            continue
        s, d = str(src).strip(), str(dst).strip()
        # dst == src means the model echoed the input, i.e. nothing was gained.
        if not s or not d or d == s:
            continue
        out[s] = d
    return out


def add_chinese(translations: Dict[str, object],
                zh_map: Dict[str, str]) -> Optional[int]:
    """Install a ``zh`` block. Returns its key count, or ``None`` if skipped."""
    if not isinstance(translations, dict):
        return None
    if not zh_map:
        return None

    english = translations.get("en")
    if not isinstance(english, dict):
        english = {}

    def tr(text: object) -> Optional[str]:
        if not isinstance(text, str):
            return None
        return zh_map.get(text.strip(), None)

    # 1. English base, translated.
    zh: Dict[str, str] = {}
    for key, value in english.items():
        got = tr(value)
        zh[key] = got if got is not None else value

    # 2. Human Simplified Chinese overrides outright.
    human_seen = 0
    for code in SIMPLIFIED:
        block = translations.get(code)
        if not isinstance(block, dict):
            continue
        for key, value in block.items():
            if isinstance(value, str) and value.strip():
                zh[key] = value
                human_seen += 1

    # 3. Anything still missing from another language gets translated too.
    for code, block in translations.items():
        if code in SIMPLIFIED or code in TRADITIONAL or code == "zh":
            continue
        if not isinstance(block, dict):
            continue
        for key, value in block.items():
            if key in zh or not isinstance(value, str):
                continue
            got = tr(value)
            zh[key] = got if got is not None else value

    if not zh:
        return None

    translations["zh"] = zh
    return len(zh)


def meta_lookup(corpus: Dict[str, str]):
    """Return a helper that maps a manifest field to its Chinese text.

    Manifest metadata was queued for translation with whitespace collapsed, so
    the same normalisation has to happen on lookup or nothing would match.
    """
    def one(text: object) -> str:
        if not isinstance(text, str):
            return ""
        key = re.sub(r"\s+", " ", text).strip()
        if not key:
            return ""
        return corpus.get(key) or ""
    return one


# Short human labels for the licence strings that actually vary. Canonical
# identifiers (CC BY 4.0, CC0, ...) are deliberately absent: rewriting those
# would make them unverifiable against the upstream record, so they pass
# through unchanged.
LICENSE_ZH = {
    "unspecified": "\u672a\u6807\u6ce8",
    "free to use": "\u53ef\u514d\u8d39\u4f7f\u7528",
    "free for research use": "\u7814\u7a76\u7528\u9014\u514d\u8d39",
    "free for research/clinical": "\u7814\u7a76/\u4e34\u5e8a\u7528\u9014\u514d\u8d39",
    "free for any use": "\u4efb\u4f55\u7528\u9014\u5747\u514d\u8d39",
    "open access": "\u5f00\u653e\u83b7\u53d6",
    "public domain": "\u516c\u6709\u9886\u57df",
    "phenx toolkit freely available protocol": "PhenX \u5de5\u5177\u5305\u534f\u8bae\uff08\u53ef\u81ea\u7531\u4f7f\u7528\uff09",
    "non-commercial research use only (zis standard terms)":
        "\u4ec5\u9650\u975e\u5546\u4e1a\u7814\u7a76\u7528\u9014\uff08ZIS \u6807\u51c6\u6761\u6b3e\uff09",
    "non-commercial research use; freely available from berkeley personality lab":
        "\u975e\u5546\u4e1a\u7814\u7a76\u7528\u9014\uff1b\u7531 Berkeley \u4eba\u683c\u5b9e\u9a8c\u5ba4\u514d\u8d39\u63d0\u4f9b",
    "free for research and professional use with attribution; not open-licensed":
        "\u7814\u7a76\u4e0e\u4e13\u4e1a\u7528\u9014\u514d\u8d39\uff0c\u9700\u4fdd\u7559\u7f72\u540d\uff1b\u975e\u5f00\u653e\u8bb8\u53ef",
    "\u00a9 pluess et al. 2024. permission granted to reproduce for personal, "
    "clinical, educational, and research purposes with citation. unauthorized "
    "modifications prohibited. contact m.pluess@surrey.ac.uk for other uses.":
        "\u00a9 Pluess \u7b49 2024\u3002\u5141\u8bb8\u5728\u4fdd\u7559\u5f15\u6ce8\u7684\u524d\u63d0\u4e0b\uff0c"
        "\u5728\u4e2a\u4eba\u3001\u4e34\u5e8a\u3001\u6559\u5b66\u4e0e\u7814\u7a76\u7528\u9014\u4e2d\u590d\u5236\u4f7f\u7528\u3002"
        "\u7981\u6b62\u672a\u7ecf\u6388\u6743\u7684\u4fee\u6539\u3002\u5176\u4ed6\u7528\u9014\u8bf7\u8054\u7cfb m.pluess@surrey.ac.uk\u3002",
}


def license_zh(text: object) -> str:
    """Chinese label for a licence string, or "" when it should stay verbatim."""
    if not isinstance(text, str):
        return ""
    key = re.sub(r"\s+", " ", text).strip().lower()
    return LICENSE_ZH.get(key, "")
