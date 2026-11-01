"""
direction.py — detect and repair inverted agreement scales in OSD bundles.

The problem
-----------
OSD pins numbers to labels: `likert_options.min` is the value of the FIRST
(leftmost) option and `labels[i]` is the text for value `min + i`
(SPECIFICATION.md, "Named Response Scales"). The runner honours that, so any
inversion lives in the data, not in the code.

A small number of bundles are authored with the agreement pole first:

    labels = ["definitely agree", ..., "definitely disagree"],  min = 0

so higher numbers mean *less* agreement — while their own scoring blocks use
the ordinary convention (+1 for the positively keyed item), and sometimes say
so in the description ("Agree scores trait for items 2, 4, 5...", "Sum of 6
items (6-30). Higher = more satisfied"). Those scales therefore score
backwards: a respondent who agrees with everything receives the minimum score.

Everything in this corpus signals the intended axis: hundreds of sibling
bundles whose first option is "Strongly disagree" and whose last is "Strongly
agree". This module finds bundles that sit on the minority side of their own
family and repairs them.

The repair
----------
1. Invert the sign of every item code in every scoring block. The published
   response order stays exactly as written — the questionnaire a participant
   sees is untouched, because ordering effects are real and the instrument is
   what it is.
2. Suppress the numeric labels for those bundles (`show_numbers: "none"`), so
   nobody is shown "0" next to "definitely agree". Stored responses keep their
   spec-conformant values.

Both the detection rule and its output are auditable: `build_data.py` writes
`data/direction-audit.json` listing every touched bundle with the evidence,
and adds `direction_repaired: true` to its manifest row.
"""

from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------
# Polarity classification of endpoint labels
# --------------------------------------------------------------------------
# Order matters: check the negative form before the positive one, because
# "disagree" contains "agree" and "inaccurate" contains "accurate".

_MODIFIERS = r"(?:very |strongly |completely |totally |slightly |somewhat |moderately |definitely |extremely |quite |mostly |fairly |rather |almost |absolutely |fully |partly )"

POLARITY: list[tuple[str, re.Pattern]] = [
    ("NEG_AGREE", re.compile(r"\bdisagree\w*\b|\bagree\w*\s+not\b", re.I)),
    ("POS_AGREE", re.compile(_MODIFIERS + r"?\bagree\w*\b", re.I)),

    ("NEG_TRUE",  re.compile(r"\b(?:false|untrue|not\s+true|incorrect)\b", re.I)),
    ("POS_TRUE",  re.compile(r"\b(?:true|correct)\b", re.I)),

    ("NEG_ACC",   re.compile(r"\binaccurate\b", re.I)),
    ("POS_ACC",   re.compile(r"\baccurate\b", re.I)),

    ("NEG_LIKE",  re.compile(r"\b(?:unlike\s+me|does\s?not\s+(?:describe|apply)|not\s+like\s+me)\b", re.I)),
    ("POS_LIKE",  re.compile(r"\b(?:like\s+me|describes\s+me|applies\s+to\s+me)\b", re.I)),

    ("NEG_FREQ",  re.compile(r"\b(?:never|not\s+at\s+all|none|rarely|seldom|no\s+difficulty)\b", re.I)),
    ("POS_FREQ",  re.compile(r"\b(?:always|constantly|every\s+day|nearly\s+every|very\s+often|often|extremely|very\s+much|a\s+great\s+deal|several\s+days)\b", re.I)),
]

OPPOSITES = {
    ("POS_AGREE", "NEG_AGREE"),
    ("POS_TRUE", "NEG_TRUE"),
    ("POS_ACC", "NEG_ACC"),
    ("POS_LIKE", "NEG_LIKE"),
    ("POS_FREQ", "NEG_FREQ"),
}

# Balance needed before a family is considered to have an established
# convention. Below this we cannot say which way round the family goes, so we
# leave it alone rather than guess.
MIN_RATIO = 5.0
MIN_TOTAL = 8


def classify(label: str) -> str | None:
    """Return the polarity class of an endpoint label, or None."""
    text = (label or "").strip()
    if not text:
        return None
    for name, pattern in POLARITY:
        if pattern.search(text):
            return name
    return None


def endpoints(definition: dict, translations: dict) -> tuple[str, str, dict] | None:
    """Return (first_label, last_label, scale_object) for the default scale."""
    if not isinstance(definition, dict):
        return None

    scale = definition.get("likert_options")
    if not isinstance(scale, dict):
        scales = definition.get("response_scales")
        if isinstance(scales, dict):
            scale = scales.get("default")
        if not isinstance(scale, dict):
            return None

    labels = scale.get("labels") or []
    if len(labels) < 2:
        return None

    english = (translations or {}).get("en") or {}
    first = english.get(labels[0])
    last = english.get(labels[-1])
    if not isinstance(first, str) or not isinstance(last, str):
        return None
    return first, last, scale


def orientation(definition: dict, translations: dict) -> tuple[str, str] | None:
    """Return (family_key, orientation) where orientation describes the poles."""
    found = endpoints(definition, translations)
    if not found:
        return None
    first, last, _ = found
    a, b = classify(first), classify(last)
    if a is None or b is None or a == b:
        return None
    if (a, b) in OPPOSITES:
        return f"{a}|{b}", "pos-first"
    if (b, a) in OPPOSITES:
        return f"{b}|{a}", "neg-first"
    return None


# --------------------------------------------------------------------------
# Corpus-wide calibration
# --------------------------------------------------------------------------
def learn_convention(scales: list[tuple[str, dict, dict]]) -> dict[str, dict]:
    """Count, for each antonym family, which pole sit at the low end."""
    tally: dict[str, dict] = {}
    for code, definition, translations in scales:
        found = orientation(definition, translations)
        if not found:
            continue
        family, direction = found
        bucket = tally.setdefault(family, {"pos-first": [], "neg-first": []})
        bucket[direction].append(code)

    convention: dict[str, dict] = {}
    for family, counts in tally.items():
        a, b = len(counts["pos-first"]), len(counts["neg-first"])
        total = a + b
        if total < MIN_TOTAL:
            continue
        majority, minority = max(a, b), min(a, b)
        if minority and majority / minority < MIN_RATIO:
            continue
        # "Thin" families rest on a handful of bundles — flag them for review
        # rather than presenting the repair as settled fact.
        confidence = "strong" if (majority >= 20 and minority >= 3) else "thin"
        convention[family] = {
            "expected": "pos-first" if a > b else "neg-first",
            "inverted": "neg-first" if a > b else "pos-first",
            "counts": {"pos-first": a, "neg-first": b},
            "confidence": confidence,
        }
    return convention


# --------------------------------------------------------------------------
# Repair
# --------------------------------------------------------------------------
def _flip_map(mapping: dict) -> tuple[dict, int]:
    flipped = 0
    out = {}
    for key, value in mapping.items():
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float)) and value != 0:
            out[key] = -value
            flipped += 1
        else:
            out[key] = value
    return out, flipped


def repair(definition: dict) -> dict:
    """Invert item coding in place so documented directions come out right.

    Returns a note describing what changed.
    """
    note = {"blocks": 0, "codes": 0, "zero": 0, "skipped": []}

    blocks = definition.get("scoring")
    iterable = blocks.items() if isinstance(blocks, dict) else enumerate(blocks or [])

    for key, spec in list(iterable):
        if not isinstance(spec, dict):
            continue

        method = str(spec.get("method") or "")
        if method in ("sum_correct", "max", "min"):
            note["skipped"].append(f"{key}:{method}")
            continue
        if spec.get("value_map"):
            # A value_map encodes its own intent; flipping around it is guesswork.
            note["skipped"].append(f"{key}:value_map")
            continue

        touched = False

        if isinstance(spec.get("items"), dict):
            spec["items"], n = _flip_map(spec["items"])
            note["codes"] += n
            touched = bool(n)
        elif isinstance(spec.get("items"), list):
            # No per-item codes: every listed item carried the implicit +1.
            spec["items"] = {item: -1 for item in spec["items"]}
            note["codes"] += len(spec["items"])
            note["zero"] += len(spec["items"])
            touched = True

        if isinstance(spec.get("item_coding"), dict):
            spec["item_coding"], n = _flip_map(spec["item_coding"])
            note["codes"] += n
            touched = touched or bool(n)

        if isinstance(spec.get("scores"), dict):
            spec["scores"], n = _flip_map(spec["scores"])
            note["codes"] += n
            touched = touched or bool(n)

        if touched:
            note["blocks"] += 1

            changed = f"Item coding inverted ({note['codes']} codes) during packaging"
            note_text = spec.get("description") or ""
            if "inverted" not in note_text.lower():
                spec["description"] = (note_text + " " + changed + ".").strip()

    return note


def nonconforming_range(definition: dict) -> dict | None:
    """Return the default scale if its numeric axis breaks the spec.

    SPECIFICATION.md requires `max == min + points - 1`. A bundle that breaks
    it (the one known case spreads 0-100 over five points) gets repaired by a
    `value_map` instead of a coding flip, because that both puts increasing
    intensity on the right value AND restores the documented spacing.
    """
    if not isinstance(definition, dict):
        return None
    scale = definition.get("likert_options")
    if not isinstance(scale, dict):
        return None
    points, low, high = scale.get("points"), scale.get("min"), scale.get("max")
    if not isinstance(points, int) or points < 2:
        return None
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return None
    if high == low + points - 1:
        return None
    return scale


def spread_map(scale: dict) -> list[float]:
    """Evenly space `points` values so the first option carries `max`."""
    points = scale["points"]
    low, high = float(scale["min"]), float(scale["max"])
    step = (high - low) / (points - 1)
    values = [round(high - i * step, 6) for i in range(points)]
    return [int(v) if v == int(v) else v for v in values]


def repair_range(definition: dict, translations: dict) -> dict:
    """Install a value_map that restores the axis; coding is left alone."""
    note = {"blocks": 0, "codes": 0}
    mapping = spread_map(definition["likert_options"])

    blocks = definition.get("scoring")
    iterable = blocks.items() if isinstance(blocks, dict) else enumerate(blocks or [])
    for _key, spec in list(iterable):
        if not isinstance(spec, dict):
            continue
        if spec.get("value_map"):
            continue
        spec["value_map"] = {"default": list(mapping)}
        note["blocks"] += 1

    first = last = ""
    found = endpoints(definition, translations)
    if found:
        first, last, _ = found
    raw = [definition["likert_options"]["min"] + i for i in range(len(mapping))]
    note["map"] = {str(r): m for r, m in zip(raw, mapping)}
    note["example"] = f"{first} -> {mapping[0]}, {last} -> {mapping[-1]}"
    return note


def suppress_numbers(definition: dict) -> bool:
    """Hide the numeric axis on repaired bundles."""
    touched = False
    scale = definition.get("likert_options")
    if isinstance(scale, dict):
        scale["show_numbers"] = "none"
        touched = True
    scales = definition.get("response_scales")
    if isinstance(scales, dict) and isinstance(scales.get("default"), dict):
        scales["default"]["show_numbers"] = "none"
        touched = True
    return touched


def describe(definition: dict, translations: dict) -> dict:
    """Human-readable evidence for one bundle."""
    found = endpoints(definition, translations)
    first = last = ""
    if found:
        first, last, _ = found
    return {"first_option": first, "last_option": last}
