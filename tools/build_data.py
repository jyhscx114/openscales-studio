#!/usr/bin/env python3
"""
build_data.py — Package OpenScales OSD scales into a zero-dependency static bundle.

Why this exists
---------------
OSD scales are raw JSON. A pure front-end app cannot `fetch()` them under the
"file://" protocol (browsers block it), so every scale is rewritten as a small
JavaScript file that assigns itself onto a global:

    (window.OS_SCALES = window.OS_SCALES || {})["PHQ9"] = { ...bundle... };

Classic <script src> tags are allowed even from file://, so double-clicking
index.html works with no server, no build step, and no network.

Usage
-----
    python3 tools/build_data.py                                  # every pack (default)
    python3 tools/build_data.py --include openscales,phenx,miss   # a subset
    python3 tools/build_data.py --source ../OpenScales --out ../dist

Packs
-----
  openscales  free / CC / public-domain instruments        (~262)
  phenx       NIH PhenX Toolkit conversions                (~420)
  ipip        IPIP item pools + translations               (~356)
  miss        Measurement Instruments for the Social Sciences (~35)
  restricted  redistribution not granted outside the project (~22)

Everything is included by default; the library view exposes the collection
each scale came from so provenance stays visible. Licences differ per scale
and are shown on every record — see OpenScales/permissions/ before any use
that goes beyond internal work.
"""

from __future__ import annotations

import direction  # inverted-agreement-scale detection/repair (see tools/direction.py)

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]")
NON_ITEM_TYPES = {
    "instruction",
    "instructions",
    "section",
    "html",
    "text",
    "note",
    "image",
    "video",
    "audio",
    "divider",
    "page_break",
    "consent",
    "caption",
}


# --------------------------------------------------------------------------
# JSON -> safe JavaScript payload
# --------------------------------------------------------------------------
def js_payload(obj) -> str:
    """Serialize to JSON then neutralise sequences that break JavaScript."""
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace("</", "<\\/")        # never terminate the enclosing script
    raw = raw.replace("\u2028", "\\u2028")  # JS line terminator (pre-ES2019 engines)
    raw = raw.replace("\u2029", "\\u2029")
    return raw


def safe_name(code: str) -> str:
    return SAFE_RE.sub("_", code)


# --------------------------------------------------------------------------
# Inspect one .osd bundle
# --------------------------------------------------------------------------
def read_bundle(path: Path):
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, dict) and "definition" in data:
        definition = data.get("definition") or {}
        translations = data.get("translations") or {}
    else:  # flat layout — definition lives at the top level
        definition = data
        translations = (data or {}).get("translations") or {}
        if isinstance(translations, dict) and not translations:
            translations = {}

    return {"osd_version": (data or {}).get("osd_version", "1.0"),
            "definition": definition,
            "translations": translations}


def count_items(definition: dict) -> int:
    items = definition.get("items") or []
    if isinstance(items, dict):  # rarely, items arrive keyed by id
        items = list(items.values())
    total = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("type", "likert")).lower() in NON_ITEM_TYPES:
            continue
        total += 1
    return total


def has_norms(definition: dict) -> bool:
    scoring = definition.get("scoring") or {}
    specs = scoring.values() if isinstance(scoring, dict) else scoring
    for spec in specs:
        if isinstance(spec, dict) and spec.get("norms"):
            return True
    return False


def summarize_scales(definition: dict):
    """Return [{id, name}] for every dimension exposed by the scale."""
    out = []
    for dim in definition.get("dimensions") or []:
        if isinstance(dim, dict):
            out.append({"id": dim.get("id"), "name": dim.get("name") or dim.get("id")})
        else:
            out.append({"id": dim, "name": dim})
    return out


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def collect_osd_files(source: Path, pack: str):
    root = source / "scales" / pack
    if not root.is_dir():
        print(f"  ! pack '{pack}' not found at {root} — skipped")
        return []
    return sorted(root.glob("*/*.osd"))


def build(source: Path, out: Path, packs: list[str], fix_direction: bool = True) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(exist_ok=True)
    (out / "data" / "scales").mkdir(exist_ok=True)
    (out / "assets").mkdir(exist_ok=True)

    manifest = []
    written_js = 0
    bytes_total = 0
    seen_codes = {}

    # Pass 1 — learn which endpoint order each label family actually uses.
    # The correction is calibrated against the corpus itself, never hardcoded.
    convention: dict[str, dict] = {}
    audit: dict[str, Any] = {}
    if fix_direction:
        print("Scanning response-scale orientations…")
        sample: list[tuple[str, dict, dict]] = []
        for pack in packs:
            for path in collect_osd_files(source, pack):
                try:
                    bundle = read_bundle(path)
                except Exception:
                    continue
                sample.append((path.stem, bundle["definition"] or {},
                               bundle.get("translations") or {}))
        convention = direction.learn_convention(sample)
        for family, info in sorted(convention.items()):
            print(f"  {family:22} expects {info['expected']:10} "
                  f"(pos-first={info['counts']['pos-first']}, "
                  f"neg-first={info['counts']['neg-first']}, "
                  f"{info['confidence']})")

    for pack in packs:
        files = collect_osd_files(source, pack)
        print(f"[{pack}] {len(files)} .osd files")
        for path in files:
            try:
                bundle = read_bundle(path)
            except Exception as exc:  # malformed JSON — report, never abort
                print(f"  ! cannot parse {path.name}: {exc}")
                continue

            definition = bundle["definition"] or {}
            translations = bundle.get("translations") or {}
            info = definition.get("scale_info") or {}
            code = info.get("code") or path.stem

            repaired = False
            pending_audit = None
            range_bug = direction.nonconforming_range(definition)

            if range_bug:
                before = direction.describe(definition, translations)
                note = direction.repair_range(definition, translations)
                direction.suppress_numbers(definition)
                repaired = True
                pending_audit = {
                    "family": "nonconforming-range",
                    "code_final": None,
                    "reason": ("max does not equal min + points - 1; installed a "
                               "value_map spreading the published endpoints across "
                               "the options, leaving display order intact"),
                    "endpoints": before,
                    "scoring_blocks": note["blocks"],
                    "codes_inverted": 0,
                    "implicit_codes": 0,
                    "value_map": note["map"],
                    "example": note["example"],
                    "skipped": [],
                    "pack": pack,
                }
            elif fix_direction and isinstance(definition, dict):
                found = direction.orientation(definition, translations)
                if found:
                    family, seen = found
                    rule = convention.get(family)
                    if rule and seen == rule["inverted"]:
                        before = direction.describe(definition, translations)
                        note = direction.repair(definition)
                        if note["blocks"]:
                            direction.suppress_numbers(definition)
                            repaired = True
                            pending_audit = {
                            "family": family,
                            "confidence": rule.get("confidence", "thin"),
                            "code_final": None,
                            "reason": ("first option is the high pole, but item coding "
                                       "follows the low-pole-first convention used by "
                                       f"{rule['counts'][rule['expected']]} sibling scales"),
                            "endpoints": before,
                            "scoring_blocks": note["blocks"],
                            "codes_inverted": note["codes"],
                            "implicit_codes": note["zero"],
                                "skipped": note["skipped"],
                                "pack": pack,
                            }
            if code in seen_codes:
                code = f"{code}__{pack}"
            seen_codes[code] = True
            if pending_audit:
                pending_audit["code_final"] = code
                audit[code] = pending_audit

            fname = safe_name(code)
            target = out / "data" / "scales" / f"{fname}.js"
            payload = js_payload(bundle)
            target.write_text(
                "(window.OS_SCALES=window.OS_SCALES||{})[" + json.dumps(code) + "]=" + payload + ";\n",
                encoding="utf-8",
            )
            written_js += 1
            size = target.stat().st_size
            bytes_total += size

            langs = sorted((bundle.get("translations") or {}).keys())
            manifest.append({
                "code": code,
                "name": info.get("name") or code,
                "abbreviation": info.get("abbreviation") or "",
                "description": info.get("description") or "",
                "citation": info.get("citation") or "",
                "license": info.get("license") or "unspecified",
                "license_url": info.get("license_url") or "",
                "license_explanation": info.get("license_explanation") or "",
                "version": info.get("version") or "",
                "url": info.get("url") or "",
                "domain": info.get("domain") or "Uncategorized",
                "items_count": count_items(definition),
                "dimensions": summarize_scales(definition),
                "languages": langs,
                "has_norms": has_norms(definition),
                "direction_repaired": repaired,
                "pack": pack,
                "file": f"data/scales/{fname}.js",
                "bytes": size,
            })

    if not manifest:
        print("No scales were built — check --source and --include.")
        return 1

    manifest.sort(key=lambda m: (m["name"] or "").lower())

    packs_meta = []
    for pack in packs:
        subset = [m for m in manifest if m["pack"] == pack]
        packs_meta.append({"id": pack, "scales": len(subset)})

    (out / "data" / "manifest.js").write_text(
        "window.OS_MANIFEST=" + js_payload(manifest) + ";\n"
        "window.OS_PACKS=" + js_payload(packs_meta) + ";\n"
        "window.OS_BUILD=" + js_payload({
            "generated_by": "OpenScales Studio build_data.py",
            "packs": packs,
            "scale_count": len(manifest),
            "languages": sorted({l for m in manifest for l in m["languages"]}),
        }) + ";\n",
        encoding="utf-8",
    )

    # Ship the runner straight out of the upstream repo so it stays in sync.
    runner_src = source / "runner"
    copies = [
        (runner_src / "scale-runner.js", out / "assets" / "scale-runner.js"),
        (runner_src / "scale-runner.css", out / "assets" / "scale-runner.css"),
    ]
    missing = False
    for src_file, dst_file in copies:
        if src_file.is_file():
            shutil.copy2(src_file, dst_file)
        else:
            print(f"  ! missing runner file: {src_file}")
            missing = True
    if missing:
        return 1

    # The double-callback guard lives in upstream's runner, but nothing stops a
    # future release from dropping it — and its loss silently duplicates every
    # session record. Fail loudly instead.
    runner_js = (out / "assets" / "scale-runner.js").read_text(encoding="utf-8")
    if "navGeneration" not in runner_js:
        print("  ! runner lost its stale-timer guard (navGeneration); refusing to build")
        return 1

    (out / "data" / "direction-audit.json").write_text(
        json.dumps({
            "note": ("Bundles whose agreement axis ran opposite to the rest of the "
                     "corpus. Item coding was inverted at build time; the response "
                     "order a participant sees was left untouched."),
            "families": convention,
            "repaired": audit,
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    langs = sorted({l for m in manifest for l in m["languages"]})
    print()
    print(f"Built {len(manifest)} scales across {len(packs)} pack(s).")
    print(f"  data/manifest.js        | {len(manifest)} entries")
    print(f"  data/scales/*.js        | {written_js} files, {bytes_total / 1048576:.1f} MB")
    if audit:
        print(f"  direction repairs       | {len(audit)} scale(s)")
        for changed in sorted(audit):
            entry = audit[changed]
            print(f"      {changed:12} {entry['endpoints']['first_option'][:26]:26} "
                  f"→ {entry['endpoints']['last_option'][:26]}")
    if not fix_direction:
        print("  direction repairs       | DISABLED (--no-fix-direction)")
    print(f"  languages         | {len(langs)} ({', '.join(langs[:12])}{'…' if len(langs) > 12 else ''})")
    print(f"  output            | {out}")
    return 0


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Build the OpenScales Studio data bundle.")
    ap.add_argument("--source", default=str(here.parent.parent / "OpenScales"),
                    help="Path to an OpenScales repository checkout.")
    ap.add_argument("--out", default=str(here.parent),
                    help="Destination directory holding index.html.")
    ap.add_argument("--include", default="openscales,phenx,ipip,miss,restricted",
                    help="Comma-separated packs; defaults to all of them.")
    ap.add_argument("--no-fix-direction", action="store_true",
                    help="Skip the inverted-agreement-scale repair (see tools/direction.py).")
    args = ap.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not (source / "scales").is_dir():
        print(f"Source does not look like an OpenScales checkout: {source}")
        print("Clone it first:  git clone https://github.com/stmueller/OpenScales.git")
        return 1

    packs = [p.strip() for p in args.include.split(",") if p.strip()]
    return build(source, Path(args.out).expanduser().resolve(), packs,
                 fix_direction=not args.no_fix_direction)


if __name__ == "__main__":
    sys.exit(main())
