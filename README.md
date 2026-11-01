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
│   └── scales/*.js         1,095 self-registering bundles, 24.2 MB total
├── tools/
│   └── build_data.py       repackages an OpenScales checkout into data/
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

## Applied fix to the vendored runner

`assets/scale-runner.js` is upstream code plus one two-line patch, marked `PATCH (OpenScales Studio)`:

> `finish()` and `terminate()` now bump `navGeneration`. A pending likert auto-advance timer could otherwise fire after the run ended and invoke the completion callback a second time, duplicating the session record.

The shell additionally refuses to record the same container twice. `vendor/runner-original/` holds the untouched files for diffing.

## Licence and attribution

- **Scale content, bundles and translations** come from OpenScales, licensed **CC BY-NC-SA 4.0** (`vendor/OPENSCALES-LICENSE.txt`) — note the **NonCommercial** and **ShareAlike** terms. Each instrument also carries its own licence, shown on its card and detail page. Internal use of this build is what it was assembled for; anything else needs a licence check first.
- `assets/scale-runner.js` / `.css` are the OpenScales runner, **MIT**.
- `app.js`, `app.css`, `index.html`, `tools/build_data.py` are **MIT**.

**Not a diagnostic tool.** These instruments support research and self-monitoring. Results require interpretation by a qualified clinician.
