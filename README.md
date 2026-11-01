# OpenScales Studio

A ready-to-run front end for the [OpenScales](https://github.com/stmueller/OpenScales) registry — **1,095 instruments** in **104 languages**, packaged locally and administered entirely in the browser.

No server. No build step. **No network access required** — everything the app needs sits in this folder.

## Quick start

```
open index.html          # macOS  — double-clicking works too
xdg-open index.html      # Linux
start index.html         # Windows
```

Or serve it on your internal network (nothing leaves the host either way):

```
python3 -m http.server 8080     # then open http://localhost:8080
```

## What it does

| | |
|---|---|
| **Library** | Search name, abbreviation, code and description; filter by collection, domain, licence and language; sort by length or "has interpretation". Paged 150 at a time. |
| **Detail view** | Full description, citation, per-scale licence and source link, declared score dimensions, optional participant ID. |
| **Administration** | Runs any OSD instrument: Likert grids, multiple choice, checkboxes, sliders, text, numeric, sections, skip logic, reversed coding, computed variables, screening gates. |
| **Scoring** | Dimension scores, interpretation labels (`Minimal`, `Moderate`, …) from each scale's own `norms.thresholds`, and a **severity gauge** that marks the score on that scale's bands. Labels resolve through the active translations. |
| **Languages** | 104 available; falls back to English per scale when a translation is missing. |
| **Theme** | Light / dark, follows the OS on first run, then remembers your choice. Dark mode covers the runner too. |
| **History** | Every session is stored in this browser only, with per-session and bulk export. |
| **Import** | Drop in your own `.osd` bundle and run it immediately. |
| **Export** | Trial-by-trial CSV, pooled wide CSV (one row per session), self-contained HTML report, raw JSON. |

Nothing is uploaded anywhere: the runner posts no results and there is no analytics code.

## Offline by construction

An audit of a full session (browse → run → score → history → import) records **8 requests, all local**, on both `http://` and `file://`. No CDN, no webfonts, no telemetry. The only `https://` strings in the source are two credit links in the footer and error text — clicking them is a deliberate act, never a load.

Two details make `file://` work:

- Browsers block `fetch()` there, so each scale is written as a classic script that registers itself: `(window.OS_SCALES = window.OS_SCALES || {})["PHQ9"] = { … }`. `<script src>` is still allowed, and bundles load lazily — one per session.
- The favicon is an inline `data:` SVG, so even the tab icon needs no request.

## Layout

```
openscales-studio/
├── index.html              shell markup — the only entry point
├── assets/
│   ├── app.js              library, routing, scoring view, history, export, theme
│   ├── app.css             shell styling (os-* classes; also re-themes the runner)
│   ├── scale-runner.js     upstream runner (MIT) + one applied fix, see below
│   └── scale-runner.css    upstream runner stylesheet
├── data/
│   ├── manifest.js         every scale's metadata as a plain assignment
│   ├── direction-audit.json  bundles whose agreement axis was repaired
│   ├── translate.sqlite3   Chinese translation corpus (item + metadata strings)
│   └── scales/*.js         1,095 self-registering bundles, Chinese included
├── tools/
│   ├── build_data.py       repackages an OpenScales checkout into data/
│   ├── direction.py        detects and repairs inverted agreement scales
│   ├── zhpack.py           folds the corpus into bundles / manifest fields
│   ├── localize.py         Chinese runner chrome, re-applied at every build
│   ├── translate.py        iFlytek Spark batch translator (SQLite job store)
│   ├── seed_meta.py        queues manifest metadata for translation
│   └── inject_zh.py        re-keys built bundles when no checkout is available
└── vendor/                 upstream material kept for offline reference
    ├── runner-original/    unmodified runner + chain-runner + scale-printer + server/
    ├── converters/         44 scripts: REDCap, Qualtrics, LimeSurvey, QTI, formr,
    │                       SurveyJS, Google Forms, PsyToolkit, ReproSchema, FHIR…
    ├── docs/               OSD 1.1.0 and OSC specifications, registry notes
    ├── templates/          OSD templates
    ├── permissions/        upstream licence evidence
    └── OPENSCALES-LICENSE.txt
```

The converters are plain Python (standard library only) and take a **directory** containing one `.osd`:

```bash
python3 vendor/converters/convert_to_redcap.py ../OpenScales/scales/openscales/PHQ9 -o phq9.xml
```

## Collections

| Pack | Scales | Contents |
|---|---|---|
| `openscales` | 262 | Free / CC / public-domain instruments |
| `phenx` | 420 | NIH PhenX Toolkit conversions |
| `ipip` | 356 | IPIP item pools, including 26 translated master pools (1,911 items each) |
| `miss` | 35 | Measurement Instruments for the Social Sciences |
| `restricted` | 22 | Redistribution outside the project is not granted |

All five are included. The library view shows each scale's collection, and every record carries its own licence with a link.

## Rebuilding the data bundle

```bash
git clone https://github.com/stmueller/OpenScales.git
python3 tools/build_data.py --source ../OpenScales          # all packs
python3 tools/build_data.py --source ../OpenScales --include openscales,phenx
```

## Chinese localisation (Simplified Chinese)

The interface is Chinese-first. Item text, option labels, scale names,
descriptions, domains and licence prose are translated; the English original
stays available (language selector, and `*_zh` fields sit beside the raw ones
in the manifest), because these are validated instruments whose English titles
are how the literature cites them.

What is translated, and how:

| Layer | Source | Count |
|---|---|---|
| Item text & response options | iFlytek Spark batch translation, folded into each bundle as a `zh` block | 93,753 keys across 1,093 scales (99.7 % of translatable strings) |
| Runner chrome (NEXT/BACK, validation, end-of-session screens) | `tools/localize.py`, re-applied at every build | 19 strings |
| Shell chrome (`index.html`, `app.js`) | hand-translated in place | — |
| Manifest metadata (names, domains, descriptions, licence prose) | same corpus pipeline via `tools/seed_meta.py` | ~2,100 strings |

Deliberately **not** translated: CC licence identifiers (`CC BY-NC-SA 4.0`),
ISO language codes shown beside their Chinese names, scale abbreviations
(`PHQ9`), citations, and the `.osd` extension.

Untranslated strings fall back to English rather than leaking a raw key — the
runner picks a whole language block, so `zh` blocks are built from the English
strings first and overridden by the corpus, and any human-authored Chinese
already in a bundle wins outright.

The translation corpus lives in `data/translate.sqlite3` (22.4 k item strings +
2.1 k metadata strings), so rebuilding never re-spends API tokens. Workflow:

```bash
python3 tools/seed_meta.py          # queue manifest metadata (idempotent)
export IFLYTEK_API_KEY=...          # Spark MaaS key
python3 tools/translate.py          # translate pending strings
python3 tools/build_data.py --source ../OpenScales
python3 tools/build_data.py --source ../OpenScales --no-zh   # skip folding
```

`tools/inject_zh.py` re-keys already-built `data/scales/*.js` in place when no
upstream checkout is reachable. Runner localisation cannot be skipped: if
upstream drifts and a literal no longer matches, the build stops instead of
shipping English chrome silently.

## Scoring-direction repairs in the data

20 bundles shipped with their agreement axis running the wrong way, so agreeing
scored the *minimum*. Both this corpus and the instruments' own text say which
way is right:

| Evidence | Example |
|---|---|
| Corpus convention | 103 bundles open with *Strongly disagree*; only 19 open with *Strongly agree* — and those 19 still use ordinary item coding |
| The bundle contradicts itself | AQ: *"Agree" scores trait for items 2, 4, 5…* while those items are coded `+1` under `labels[0] = "definitely agree"`, `min = 0` |
| The bundle contradicts itself | PSQ-III: *"Sum of 6 items (6-30). Higher = more satisfied"* but agreeing yields 1, not 5 |
| The published key | SWLS runs 5–35 with higher = more satisfied; CBI maps Always…Never to 100/75/50/25/0 |

The runner was never at fault: `SPECIFICATION.md` pins `min` to the leftmost
option and defines `reversed = (min + max) − response`, and the runner follows
both exactly. The defect is in the bundles.

`tools/direction.py` fixes it at build time:

1. **Invert every item code** in every scoring block. The response order shown
   to participants is untouched — ordering effects are real, and printing the
   options the way the instrument prints them is the whole point.
2. **Hide the numeric axis** on those bundles (`show_numbers: "none"`), so
   nobody is offered "0" next to *definitely agree*. Stored responses keep their
   spec-conformant values.
3. **CBI gets a `value_map`** instead: it is the only bundle whose axis breaks
   the spec (`max` must equal `min + points − 1`), which is also why its
   published 100/75/50/25/0 spacing had collapsed.

Detection is calibrated against the corpus rather than hardcoded — a family is
only judged once enough bundles vote, and families with thin support are marked
`confidence: thin` for review (`SDRS5`, `PX180701`).

Every touched bundle is listed in **`data/direction-audit.json`** with its
endpoints, evidence and the exact number of inverted codes; affected rows in
`manifest.js` carry `direction_repaired: true` and render a **scoring fixed**
badge in the UI. Review with:

```bash
python3 -c "import json;print('\n'.join(json.load(open('data/direction-audit.json'))['repaired']))"
python3 tools/build_data.py --source ../OpenScales --no-fix-direction   # opt out
```

Verification runs the real instrument in a browser and checks the totals
against published keys: AQ all-disagree → **78**, all-agree → **72**;
SWLS all-agree → **35**, all-disagree → **5**; CBI all-Always → **100**,
all-Never → **0**.

## Applied fix to the vendored runner

`assets/scale-runner.js` carries one guard the upstream double-callback bug
needs: `finish()` and `terminate()` bump `navGeneration`, so a pending likert
auto-advance timer cannot fire after the run ends and invoke the completion
callback twice (which used to write two records per session). The shell also
refuses to record the same container twice.

`build_data.py` asserts the guard survives each rebuild, so an upstream release
that drops it fails the build instead of silently corrupting history again.
`vendor/runner-original/` holds the reference copy for diffing.

## Licence and attribution

- **Scale content, bundles and translations** come from OpenScales, licensed **CC BY-NC-SA 4.0** (`vendor/OPENSCALES-LICENSE.txt`) — note the **NonCommercial** and **ShareAlike** terms. Each instrument also carries its own licence, shown on its card and detail page. Internal use of this build is what it was assembled for; anything else needs a licence check first.
- `assets/scale-runner.js` / `.css` are the OpenScales runner, **MIT**.
- `app.js`, `app.css`, `index.html`, `tools/build_data.py` are **MIT**.

**Not a diagnostic tool.** These instruments support research and self-monitoring. Results require interpretation by a qualified clinician.
