"""Simplified-Chinese UI localisation applied to the vendored runner at build time.

Why this exists
---------------
``build_data.py`` copies ``scale-runner.js`` straight from the OpenScales
checkout, so any hand edit to ``assets/scale-runner.js`` is erased on the next
build. These strings therefore live here and are re-applied every time, exactly
like the scoring-direction repair.

Each entry is a literal that upstream renders when a bundle supplies no
translation key of its own. A few (``next_label``, ``back_label``,
``skip_label``, ``terminate_heading``) can still be overridden per bundle; the
rest are hardcoded English in upstream and have no bundle-level escape hatch,
which is the whole reason this layer exists.

Every replacement must hit exactly once. A miss means upstream drifted and
localised UI would silently revert to English, so the build stops instead.
"""

from __future__ import annotations

from typing import List, Tuple

# (upstream literal, Simplified Chinese)
REPLACEMENTS: List[Tuple[str, str]] = [
    # Navigation and progress
    ("strings['back_label'] || 'BACK'", "strings['back_label'] || '\u4e0a\u4e00\u9898'"),
    ("strings['skip_label'] || 'SKIP'", "strings['skip_label'] || '\u8df3\u8fc7'"),
    ("strings['next_label'] || 'NEXT'", "strings['next_label'] || '\u4e0b\u4e00\u9898'"),
    ("`${answered} of ${total}`", "`\u7b2c ${answered} \u9898 / \u5171 ${total} \u9898`"),

    # Validation messages
    ("'This question requires an answer.'", "'\u6b64\u9898\u4e3a\u5fc5\u7b54\u3002'"),
    ("'Please enter a valid number.'", "'\u8bf7\u8f93\u5165\u6709\u6548\u6570\u5b57\u3002'"),
    ("`Please enter a value of ${numMin} or more.`",
     "`\u8bf7\u8f93\u5165\u4e0d\u5c0f\u4e8e ${numMin} \u7684\u503c\u3002`"),
    ("`Please enter a value of ${numMax} or less.`",
     "`\u8bf7\u8f93\u5165\u4e0d\u5927\u4e8e ${numMax} \u7684\u503c\u3002`"),
    ("result.error || 'Please answer this question.'",
     "result.error || '\u8bf7\u5148\u56de\u7b54\u672c\u9898\u3002'"),

    # End-of-session screens
    ("strings['terminate_heading'] || 'Session Ended'",
     "strings['terminate_heading'] || '\u65bd\u6d4b\u5df2\u7ed3\u675f'"),
    ("'Thank you. Based on your responses you are not eligible to continue.'",
     "'\u611f\u8c22\u53c2\u4e0e\u3002\u6839\u636e\u4f60\u7684\u4f5c\u7b54\uff0c\u4f60\u4e0d\u7b26\u5408\u7ee7\u7eed\u4f5c\u7b54\u7684\u6761\u4ef6\u3002'"),
    ("'Thank you!'", "'\u611f\u8c22\u53c2\u4e0e\uff01'"),
    ("'Please contact the researcher.'", "'\u8bf7\u8054\u7cfb\u7814\u7a76\u4eba\u5458\u3002'"),

    # Exports (hidden behind hideDownloads in Studio, kept for imported bundles)
    ("'Download report'", "'\u4e0b\u8f7d\u62a5\u544a'"),
    ("'Download trial-by-trial data'", "'\u4e0b\u8f7d\u9010\u9898\u6570\u636e'"),

    # Demo-mode notices
    ("'\U0001F50D <strong>Demo mode</strong> \u2014 responses are not saved or uploaded.'",
     "'\U0001F50D <strong>\u6f14\u793a\u6a21\u5f0f</strong> \u2014 \u4f5c\u7b54\u4e0d\u4f1a\u4fdd\u5b58\u6216\u4e0a\u4f20\u3002'"),
    ("'<p><em>Demo mode \u2014 data was not uploaded to a server.</em></p>'",
     "'<p><em>\u6f14\u793a\u6a21\u5f0f \u2014 \u6570\u636e\u672a\u4e0a\u4f20\u5230\u670d\u52a1\u5668\u3002</em></p>'"),

    # Loading indicator and media fallback
    ("'<span class=\"sr-spinner\"></span><p>Loading\u2026</p>'",
     "'<span class=\"sr-spinner\"></span><p>\u52a0\u8f7d\u4e2d\u2026</p>'"),
    ("'[image not loaded \u2014 remote media not permitted]'",
     "'[\u56fe\u7247\u672a\u80fd\u52a0\u8f7d\u2014\u2014\u5df2\u7981\u6b62\u52a0\u8f7d\u8fdc\u7a0b\u5a92\u4f53]'"),
]


def apply(text: str) -> Tuple[str, List[str]]:
    """Rewrite every known upstream literal. Returns the text and any misses."""
    misses: List[str] = []
    for old, new in REPLACEMENTS:
        hits = text.count(old)
        if hits != 1:
            misses.append(f"{hits} match(es) for {old[:60]}")
            continue
        text = text.replace(old, new)
    return text, misses
