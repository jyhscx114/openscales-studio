/* ============================================================
   OpenScales Studio — application shell
   Zero dependencies, zero build step. Works over file:// too:
   bundled data arrives as classic <script> assignments, never fetch().
   ============================================================ */
(function () {
  'use strict';

  var HISTORY_KEY = 'os_studio.history.v1';
  var LANG_KEY    = 'os_studio.lang';
  var HISTORY_MAX = 200;

  var state = {
    view: 'library',
    arg: null,
    manifest: [],
    languages: [],
    filters: { q: '', pack: '', domain: '', license: '', lang: '', sort: 'name' },
    limit: 150,
    lang: 'en',
    bundle: null,        // currently loaded OSD bundle
    bundleCode: null,
    imported: null,      // bundle dropped in via the Import view
    history: []
  };

  // ── tiny helpers ─────────────────────────────────────────
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function debounce(fn, wait) {
    var t; return function () {
      var args = arguments, self = this;
      clearTimeout(t); t = setTimeout(function () { fn.apply(self, args); }, wait);
    };
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('Cannot load ' + src)); };
      document.head.appendChild(s);
    });
  }

  function pad(n) { return String(n).padStart(2, '0'); }

  function stamp(ts) {
    var d = new Date(ts);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
           ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function newParticipant() {
    return 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }

  function download(filename, content, mime) {
    var blob = new Blob([content], { type: mime || 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  // Only http(s) / mailto survive — scale metadata is bundled data, but never
  // trust a string that lands directly inside an href.
  function safeUrl(u) {
    if (!u) return '';
    return /^(https?:|mailto:)/i.test(u) ? u : '';
  }

  function langName(code) {    try {
      return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) || code.toUpperCase();
    } catch (e) { return code.toUpperCase(); }
  }

  // ── storage ──────────────────────────────────────────────
  function readStore(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }

  function writeStore(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch (e) { return false; }
  }

  // ── data access ──────────────────────────────────────────
  function getScale(code) {
    for (var i = 0; i < state.manifest.length; i++) {
      if (state.manifest[i].code === code) return state.manifest[i];
    }
    return null;
  }

  var bundleCache = {};

  function loadBundle(meta) {
    if (!meta) return Promise.reject(new Error('Unknown scale'));
    if (bundleCache[meta.code]) return Promise.resolve(bundleCache[meta.code]);
    if (!window.OS_SCALES) window.OS_SCALES = {};
    if (window.OS_SCALES[meta.code]) {
      bundleCache[meta.code] = window.OS_SCALES[meta.code];
      return Promise.resolve(bundleCache[meta.code]);
    }
    return loadScript(meta.file).then(function () {
      var b = window.OS_SCALES && window.OS_SCALES[meta.code];
      if (!b) throw new Error('Bundle missing for ' + meta.code);
      bundleCache[meta.code] = b;
      return b;
    });
  }

  // ── scoring interpretation ───────────────────────────────
  function scoringSpec(definition, dimId) {
    var scoring = definition && definition.scoring;
    if (!scoring) return null;
    if (Array.isArray(scoring)) {
      for (var i = 0; i < scoring.length; i++) {
        var s = scoring[i];
        if (s && (s.id === dimId || s.dimension === dimId)) return s;
      }
      return null;
    }
    return scoring[dimId] || null;
  }

  function interpret(definition, strings, dimId, value) {
    var spec = scoringSpec(definition, dimId);
    if (!spec || !spec.norms || !spec.norms.thresholds) return null;
    var list = spec.norms.thresholds;

    // Resolve labels once — they may be literal strings or translation keys.
    var bands = list.map(function (t) {
      var label = t.label;
      if (!label && t.label_key && strings) label = strings[t.label_key];
      return {
        label: label || '',
        min: (t.min === undefined || t.min === null) ? null : t.min,
        max: (t.max === undefined || t.max === null) ? null : t.max
      };
    });

    var hit = -1;
    if (typeof value === 'number' && !isNaN(value)) {
      for (var i = 0; i < bands.length; i++) {
        var min = bands[i].min === null ? -Infinity : bands[i].min;
        var max = bands[i].max === null ? Infinity : bands[i].max;
        if (value >= min && value <= max) { hit = i; break; }
      }
    }
    return { label: hit >= 0 ? bands[hit].label : '', note: spec.norms.source || '', bands: bands, hit: hit };
  }

  // Severity gauge: the scale's own bands, with the observed score marked.
  function gaugeHTML(interp, value) {
    if (!interp || !interp.bands || interp.bands.length < 2) return '';
    var b = interp.bands;
    var lo = b[0].min === null ? 0 : b[0].min;
    var hi = b[b.length - 1].max === null ? (b[b.length - 1].min + 1) : b[b.length - 1].max;
    if (!(hi > lo) || typeof value !== 'number' || isNaN(value)) return '';

    var segs = b.map(function (t, i) {
      var a = Math.max(t.min === null ? lo : t.min, lo);
      var z = Math.min(t.max === null ? hi : t.max, hi);
      var w = Math.max(0, (z - a) / (hi - lo) * 100);
      return '<span class="gauge-seg' + (i === interp.hit ? ' is-hit' : '') +
             '" style="width:' + w.toFixed(2) + '%" title="' + esc(t.label) + '"></span>';
    }).join('');

    var pct = Math.min(100, Math.max(0, (value - lo) / (hi - lo) * 100));
    return '<div class="gauge">' +
             '<div class="gauge-track">' + segs +
               '<span class="gauge-cursor" style="left:' + pct.toFixed(2) + '%"></span>' +
             '</div>' +
             '<div class="gauge-labels"><span>' + esc(b[0].label || lo) + '</span>' +
               '<span>' + esc(b[b.length - 1].label || hi) + '</span></div>' +
           '</div>';
  }

  function dimensionLabel(definition, dimId) {
    var dims = (definition && definition.dimensions) || [];
    for (var i = 0; i < dims.length; i++) {
      var d = dims[i];
      if (d && (d === dimId || d.id === dimId)) {
        return (d && d.name) || dimId;
      }
    }
    return dimId;
  }

  // ── routing ──────────────────────────────────────────────
  function currentHash() {
    var h = (location.hash || '').replace(/^#\/?/, '');
    var parts = h.split('/');
    return { view: parts[0] || 'library', arg: parts[1] ? decodeURIComponent(parts[1]) : null };
  }

  function setHash(view, arg) {
    var next = '#/' + view + (arg ? '/' + encodeURIComponent(arg) : '');
    if (location.hash === next) { applyRoute(); return; }
    location.hash = next;
  }

  function applyRoute() {
    var r = currentHash();
    var known = ['library', 'scale', 'run', 'history', 'import'];
    if (known.indexOf(r.view) < 0) r = { view: 'library', arg: null };
    state.view = r.view;
    state.arg = r.arg;

    $$('.view').forEach(function (v) { v.hidden = true; });
    $$('#nav a').forEach(function (a) {
      a.classList.toggle('is-active', a.dataset.view === r.view);
    });

    if (r.view === 'library') renderLibrary();
    if (r.view === 'scale')   renderDetail(r.arg);
    if (r.view === 'run')     renderRun(r.arg || state.bundleCode);
    if (r.view === 'history') renderHistory();
    if (r.view === 'import')  { /* static markup */ }

    if (r.view === 'run' && !r.arg && !state.bundleCode) { setHash('library'); return; }

    $('#view-' + (r.view === 'scale' ? 'detail' : r.view)).hidden = false;
    window.scrollTo(0, 0);
  }

  // ── library ──────────────────────────────────────────────
  function filtered() {
    var f = state.filters;
    var q = f.q.trim().toLowerCase();
    var list = state.manifest.filter(function (m) {
      if (f.pack && m.pack !== f.pack) return false;
      if (f.domain && m.domain !== f.domain) return false;
      if (f.license && m.license !== f.license) return false;
      if (f.lang && m.languages.indexOf(f.lang) < 0) return false;
      if (!q) return true;
      var hay = (m.name + ' ' + m.abbreviation + ' ' + m.code + ' ' +
                 m.domain + ' ' + m.description).toLowerCase();
      return hay.indexOf(q) >= 0;
    });

    if (f.sort === 'norms') {
      list = list.filter(function (m) { return m.has_norms; });
    } else if (f.sort === 'items-asc') {
      list.sort(function (a, b) { return a.items_count - b.items_count; });
    } else if (f.sort === 'items-desc') {
      list.sort(function (a, b) { return b.items_count - a.items_count; });
    } else {
      list.sort(function (a, b) { return a.name.localeCompare(b.name); });
    }
    return list;
  }

  function cardHTML(m) {
    var langs = m.languages.length > 4
      ? m.languages.length + ' languages'
      : m.languages.join(' · ');
    return '' +
      '<article class="card scale-card" data-code="' + esc(m.code) + '">' +
        '<div class="meta-row">' +
          '<span class="chip chip-code">' + esc(m.code) + '</span>' +
          '<span class="chip">' + esc(m.domain) + '</span>' +
          (m.pack !== 'openscales' ? '<span class="chip chip-soft">' + esc(m.pack) + '</span>' : '') +
          (m.has_norms ? '<span class="chip chip-good">interpretation</span>' : '') +
          (m.direction_repaired ? '<span class="chip chip-repair">scoring fixed</span>' : '') +
        '</div>' +
        '<h3>' + esc(m.abbreviation ? m.abbreviation + ' — ' + m.name : m.name) + '</h3>' +
        '<p class="desc">' + esc(m.description || 'No description provided.') + '</p>' +
        '<div class="meta-row">' +
          '<span class="chip chip-soft">' + m.items_count + ' items</span>' +
          '<span class="chip chip-soft">' + esc(langs) + '</span>' +
          '<span class="chip chip-soft">' + esc(m.license) + '</span>' +
        '</div>' +
      '</article>';
  }

  function renderLibrary() {
    var list = filtered();
    var slice = list.slice(0, state.limit);
    $('#resultCount').textContent = slice.length === list.length
      ? list.length + ' scales'
      : 'showing ' + slice.length + ' of ' + list.length + ' scales';
    $('#emptyState').hidden = list.length > 0;
    $('#grid').innerHTML = slice.map(cardHTML).join('');

    // Stagger the entrance so a 150-card page does not land all at once.
    $$('#grid .scale-card').forEach(function (el, i) {
      el.style.animationDelay = Math.min(i, 24) * 14 + 'ms';
    });

    var more = $('#moreWrap');
    more.hidden = slice.length >= list.length;
    if (!more.hidden) {
      $('#moreNote').textContent = (list.length - slice.length) + ' more';
    }
  }

  function buildFilters() {
    var domains = {}, licenses = {}, langs = {}, packs = {};
    state.manifest.forEach(function (m) {
      domains[m.domain] = (domains[m.domain] || 0) + 1;
      licenses[m.license] = (licenses[m.license] || 0) + 1;
      packs[m.pack] = (packs[m.pack] || 0) + 1;
      m.languages.forEach(function (l) { langs[l] = (langs[l] || 0) + 1; });
    });

    function opts(obj, labelFn) {
      return Object.keys(obj).sort(function (a, b) { return obj[b] - obj[a]; })
        .slice(0, 120)
        .map(function (k) { return '<option value="' + esc(k) + '">' + esc(labelFn(k)) + ' (' + obj[k] + ')</option>'; })
        .join('');
    }

    $('#fPack').insertAdjacentHTML('beforeend', opts(packs, function (k) { return k; }));
    $('#fDomain').insertAdjacentHTML('beforeend', opts(domains, function (k) { return k; }));
    $('#fLicense').insertAdjacentHTML('beforeend', opts(licenses, function (k) { return k; }));
    $('#fLang').insertAdjacentHTML('beforeend', opts(langs, langName));

    $('#fPack').value = state.filters.pack;
    $('#fDomain').value = state.filters.domain;
    $('#fLicense').value = state.filters.license;
    $('#fLang').value = state.filters.lang;
    $('#fSort').value = state.filters.sort;
    $('#q').value = state.filters.q;
  }

  function renderStats() {
    var packs = (window.OS_PACKS || []).length;
    var rows = [
      [state.manifest.length, 'scales'],
      [state.languages.length, 'languages'],
      [packs, 'collections'],
      ['0', 'network calls']
    ];
    $('#stats').innerHTML = rows.map(function (r) {
      var v = typeof r[0] === 'number' ? r[0].toLocaleString() : r[0];
      return '<div><b>' + esc(v) + '</b><span>' + esc(r[1]) + '</span></div>';
    }).join('');
  }

  function initTheme() {
    var btn = $('#themeToggle');
    if (!btn) return;
    if (!document.documentElement.getAttribute('data-theme')) {
      document.documentElement.setAttribute('data-theme', 'light');
    }
    btn.addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('os_studio.theme', next); } catch (e) { /* private mode */ }
    });
  }

  function initLanguages() {
    var sel = $('#langSelect');
    state.languages.sort();
    sel.innerHTML = state.languages.map(function (l) {
      return '<option value="' + esc(l) + '">' + esc(langName(l)) + ' (' + esc(l) + ')</option>';
    }).join('');
    sel.value = state.lang;
  }

  // ── detail ───────────────────────────────────────────────
  // Bundles whose agreement axis ran against the rest of the corpus. Say so
  // out loud: a reviewer must be able to see that we touched the scoring.
  function repairNote(m) {
    if (!m.direction_repaired) return '';
    return 'Scoring note — this bundle shipped with its agreement options '
         + 'reversed relative to the convention used elsewhere in the library, '
         + 'so agreeing scored the minimum. Item coding was inverted at build '
         + 'time; the response order shown to participants is unchanged. '
         + 'See data/direction-audit.json.';
  }

  function renderDetail(code) {
    var m = getScale(code);
    var host = $('#view-detail');
    if (!m) {
      host.innerHTML = '<div class="card" style="padding:24px"><h2>Scale not found</h2>' +
        '<p><a href="#/library">Back to library</a></p></div>';
      return;
    }

    var dims = (m.dimensions || []).map(function (d) {
      return '<li><span>' + esc(d.name || d.id) + '</span><code>' + esc(d.id) + '</code></li>';
    }).join('');

    host.innerHTML = '' +
      '<div class="card" style="padding:10px 0 0;margin-bottom:14px;border:0;background:none;box-shadow:none">' +
        '<button class="back" type="button" data-action="to-library">← Back to library</button>' +
      '</div>' +
      '<div class="detail-grid">' +
        '<div class="card detail-main">' +
          '<h2>' + esc(m.name) + '</h2>' +
          '<p class="detail-sub">' + esc(m.code) + (m.abbreviation ? ' · ' + esc(m.abbreviation) : '') +
            ' · ' + m.items_count + ' items · ' + esc(m.license) + '</p>' +
          '<div class="detail-body">' +
            '<p>' + esc(m.description || 'No description provided.') + '</p>' +
            (repairNote(m) ? '<p class="repair-note">' + esc(repairNote(m)) + '</p>' : '') +
            (m.citation ? '<p class="citation">' + esc(m.citation) + '</p>' : '') +
            (m.license_explanation ? '<p class="citation"><em>' + esc(m.license_explanation) + '</em></p>' : '') +
          '</div>' +
          '<div class="actions">' +
            '<button class="primary" type="button" data-action="start" data-code="' + esc(m.code) + '">Start administration</button>' +
            '<input id="participantInput" type="text" placeholder="Participant ID (optional)" maxlength="40">' +
            (safeUrl(m.url) ? '<a class="chip chip-accent" style="padding:8px 12px" href="' + esc(m.url) + '" target="_blank" rel="noopener">Source</a>' : '') +
            (safeUrl(m.license_url) ? '<a class="chip" style="padding:8px 12px" href="' + esc(m.license_url) + '" target="_blank" rel="noopener">Licence</a>' : '') +
          '</div>' +
        '</div>' +
        '<aside class="card detail-side">' +
          '<dl class="kv">' +
            '<dt>Domain</dt><dd>' + esc(m.domain) + '</dd>' +
            '<dt>Version</dt><dd>' + esc(m.version || '—') + '</dd>' +
            '<dt>Languages</dt><dd>' + m.languages.length + '</dd>' +
            '<dt>Items</dt><dd>' + m.items_count + '</dd>' +
          '</dl>' +
          '<h4 style="margin:18px 0 0;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px">Score dimensions</h4>' +
          '<ul class="dim-list">' + (dims || '<li><span>Not declared</span></li>') + '</ul>' +
        '</aside>' +
      '</div>';
  }

  // ── run ──────────────────────────────────────────────────
  function renderRun(code, importedBundle, importedName) {
    var host = $('#runnerHost');
    var result = $('#resultCard');
    result.hidden = true;
    result.innerHTML = '';
    $('#runCode').textContent = importedName || code;
    $('#runLang').textContent = state.lang;

    var meta = getScale(code);

    // An imported bundle survives re-entry through the router (hashchange
    // re-renders the run view with no arguments), so keep it on the state.
    if (importedBundle) state.imported = { code: code, bundle: importedBundle };
    var fromImport = (state.imported && state.imported.code === code) ? state.imported.bundle : null;

    var boot = fromImport ? Promise.resolve(fromImport)
             : meta ? loadBundle(meta)
             : Promise.reject(new Error('Scale "' + code + '" is not part of this bundle.'));

    host.innerHTML = '<div class="sr-loading"><span class="sr-spinner"></span><p>Loading…</p></div>';

    boot.then(function (bundle) {
      state.bundle = bundle;
      state.bundleCode = code;
      mountRunner(bundle, code);
    }).catch(function (err) {
      host.innerHTML = '<div class="sr-error-fatal"><strong>Cannot load this scale.</strong><br>' +
        esc(err.message) + '</div>';
    });
  }

  function mountRunner(bundle, code) {
    var host = $('#runnerHost');
    host.innerHTML = '';

    var participant = newParticipant();
    var container = document.createElement('div');
    host.appendChild(container);

    var osdText = JSON.stringify(bundle);
    var blobURL = URL.createObjectURL(new Blob([osdText], { type: 'application/json' }));

    ScaleRunner.mount(container, {
      osdURL: blobURL,
      participant: participant,
      language: state.lang,
      demo: true,
      collectURL: null,
      hideDownloads: true,
      showTitle: false,
      onComplete: function (detail) {
        setTimeout(function () { URL.revokeObjectURL(blobURL); }, 4000);
        var data = container._scaleData || {};
        showResult({
          bundle: bundle,
          code: code,
          detail: detail,
          scaleData: data,
          container: container,
          participant: participant
        });
      }
    });
  }

  function showResult(ctx) {
    // One ambush proof guard: a run can emit the completion callback more than
    // once (upstream auto-advance races), so never record the same container twice.
    if (ctx.container && ctx.container.dataset.osDone === '1') return;
    if (ctx.container) ctx.container.dataset.osDone = '1';
    var definition = (ctx.bundle && ctx.bundle.definition) || {};
    var strings = ((ctx.bundle && ctx.bundle.translations) || {})[state.lang] ||
                  ((ctx.bundle && ctx.bundle.translations) || {}).en || {};
    var scores = (ctx.detail && ctx.detail.scores) || {};
    var computed = (ctx.detail && ctx.detail.computed) || {};

    var record = {
      id: ctx.detail.participant + '-' + Date.now(),
      code: ctx.code,
      name: (definition.scale_info && definition.scale_info.name) || ctx.code,
      participant: ctx.detail.participant,
      lang: state.lang,
      ts: Date.now(),
      status: ctx.detail.status,
      scores: scores,
      computed: computed,
      responses: ctx.detail.responses || {},
      pooled: { hdr: ctx.scaleData.pooledHdr || '', line: ctx.scaleData.pooledLine || '' }
    };
    addHistory(record);

    var boxes = Object.keys(scores).map(function (dimId) {
      var val = scores[dimId];
      var interp = interpret(definition, strings, dimId, val);
      var spec = scoringSpec(definition, dimId) || {};
      return '' +
        '<div class="score-box">' +
          '<div class="label">' + esc(dimensionLabel(definition, dimId)) + '</div>' +
          '<div class="value">' + esc(fmtNum(val)) + '</div>' +
          (interp && interp.label ? '<div class="interp">' + esc(interp.label) + '</div>' : '') +
          gaugeHTML(interp, val) +
          '<div class="note">' + esc(spec.description ? shortDesc(spec.description) : (interp && interp.note ? interp.note : '')) + '</div>' +
        '</div>';
    }).join('');

    var computedRows = Object.keys(computed).map(function (k) {
      return '<tr><th>' + esc(k) + '</th><td>' + esc(fmtNum(computed[k])) + '</td></tr>';
    }).join('');

    var nResp = Object.keys(record.responses).length;

    var card = $('#resultCard');
    card.hidden = false;
    card.innerHTML = '' +
      '<h2>' + esc(record.name) + '</h2>' +
      '<p class="sub">Participant <code>' + esc(record.participant) + '</code> · ' +
        stamp(record.ts) + ' · ' + nResp + ' responses · status ' + esc(record.status) + '</p>' +
      (boxes ? '<div class="score-grid">' + boxes + '</div>'
             : '<p class="sub">This instrument declares no numeric dimensions.</p>') +
      (computedRows ? '<table class="raw"><tbody>' + computedRows + '</tbody></table>' : '') +
      '<div class="actions">' +
        '<button class="ghost" type="button" data-action="export-csv">Trial data (CSV)</button>' +
        '<button class="ghost" type="button" data-action="export-pooled">Summary row (CSV)</button>' +
        '<button class="ghost" type="button" data-action="export-report">Report (HTML)</button>' +
        '<button class="ghost" type="button" data-action="export-json">Session (JSON)</button>' +
        '<button class="primary" type="button" data-action="again" data-code="' + esc(ctx.code) + '">Run again</button>' +
        '<button class="ghost" type="button" data-action="to-history">History</button>' +
      '</div>';

    card._record = record;
    card._scaleData = ctx.scaleData;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function fmtNum(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number') return Math.round(v * 100) / 100;
    return v;
  }

  function shortDesc(s) {
    var t = String(s).replace(/\s+/g, ' ');
    return t.length > 160 ? t.slice(0, 157) + '…' : t;
  }

  // ── history ──────────────────────────────────────────────
  function addHistory(record) {
    state.history.unshift(record);
    if (state.history.length > HISTORY_MAX) state.history.length = HISTORY_MAX;
    writeStore(HISTORY_KEY, state.history);
  }

  function renderHistory() {
    var host = $('#historyList');
    if (!state.history.length) {
      host.innerHTML = '<div class="card empty"><p>No sessions recorded yet.</p>' +
        '<p><a href="#/library">Open the library</a> to run a scale.</p></div>';
      return;
    }
    host.innerHTML = state.history.map(function (h) {
      var chips = Object.keys(h.scores || {}).map(function (k) {
        return '<span class="chip">' + esc(k) + ': ' + esc(fmtNum(h.scores[k])) + '</span>';
      }).join('');
      return '' +
        '<article class="card hist-item" data-id="' + esc(h.id) + '">' +
          '<div class="top">' +
            '<h3>' + esc(h.name) + '</h3>' +
            '<span class="chip chip-code">' + esc(h.code) + '</span>' +
            '<span class="chip chip-soft">' + esc(h.lang) + '</span>' +
            (h.status === 'completed' ? '' : '<span class="chip">' + esc(h.status) + '</span>') +
            '<span class="when">' + esc(stamp(h.ts)) + '</span>' +
          '</div>' +
          '<div class="scores">' + (chips || '<span class="chip chip-soft">no dimensions</span>') + '</div>' +
          '<div class="ops">' +
            '<button class="ghost" type="button" data-action="hist-csv">CSV</button>' +
            '<button class="ghost" type="button" data-action="hist-json">JSON</button>' +
            '<button class="ghost danger" type="button" data-action="hist-del">Delete</button>' +
          '</div>' +
        '</article>';
    }).join('');
  }

  function exportAllCSV() {
    var rows = state.history.filter(function (h) { return h.pooled && h.pooled.line; });
    if (!rows.length) { alert('No pooled rows captured yet.'); return; }
    var out = [rows[0].pooled.hdr].concat(rows.map(function (h) { return h.pooled.line; }));
    download('openscales-history.csv', out.join('\r\n') + '\r\n', 'text/csv;charset=utf-8');
  }

  // ── import ───────────────────────────────────────────────
  function runImported(text, filename) {
    var err = $('#importError');
    err.hidden = true;
    var bundle;
    try { bundle = JSON.parse(text); }
    catch (e) { err.textContent = 'Not valid JSON: ' + e.message; err.hidden = false; return; }

    if (!bundle || typeof bundle !== 'object') {
      err.textContent = 'Expected a JSON object.'; err.hidden = false; return;
    }
    if (!bundle.definition) {
      if (bundle.items) bundle = { bundle_version: 'imported', definition: bundle, translations: {} };
      else { err.textContent = 'Missing a "definition" key — this is not an OSD bundle.'; err.hidden = false; return; }
    }

    var code = (bundle.definition.scale_info && bundle.definition.scale_info.code) ||
               String(filename || 'imported').replace(/\.(osd|json)$/i, '');
    setHash('run', code);
    renderRun(code, bundle, code);
  }

  function initImport() {
    var zone = $('#dropzone');
    var input = $('#fileInput');

    input.addEventListener('change', function () {
      var f = input.files && input.files[0];
      if (!f) return;
      var fr = new FileReader();
      fr.onload = function () { runImported(String(fr.result), f.name); };
      fr.onerror = function () {
        var err = $('#importError');
        err.textContent = 'Could not read that file.'; err.hidden = false;
      };
      fr.readAsText(f);
      input.value = '';
    });

    ['dragenter', 'dragover'].forEach(function (evt) {
      zone.addEventListener(evt, function (e) { e.preventDefault(); zone.classList.add('is-over'); });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
      zone.addEventListener(evt, function (e) { e.preventDefault(); zone.classList.remove('is-over'); });
    });
    zone.addEventListener('drop', function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) return;
      var fr = new FileReader();
      fr.onload = function () { runImported(String(fr.result), f.name); };
      fr.readAsText(f);
    });
  }

  // ── event wiring ─────────────────────────────────────────
  function delegate(e) {
    var el = e.target.closest('[data-action]');
    if (!el) return;
    var action = el.dataset.action;
    var card = null;

    if (action === 'to-library') { setHash('library'); }
    if (action === 'to-detail')  {
      if (getScale(state.bundleCode)) setHash('scale', state.bundleCode); else setHash('library');
    }
    if (action === 'to-history') { setHash('history'); }
    if (action === 'reset')      { resetAll(); }
    if (action === 'more')       { state.limit += 150; renderLibrary(); }
    if (action === 'start') {
      setHash('run', el.dataset.code);
    }
    if (action === 'again') {
      var host = $('#runnerHost');
      var result = $('#resultCard');
      result.hidden = true; result.innerHTML = '';
      host.scrollIntoView({ behavior: 'smooth', block: 'start' });
      mountRunner(state.bundle, el.dataset.code);
    }
    if (action === 'export-csv' || action === 'export-pooled' ||
        action === 'export-report' || action === 'export-json') {
      card = $('#resultCard');
      var rec = card._record, sd = card._scaleData || {};
      if (!rec) return;
      var base = rec.code + '-' + rec.participant;
      if (action === 'export-csv') {
        download(base + '.csv', (sd.csvLines || []).join('\r\n') + '\r\n', 'text/csv;charset=utf-8');
      } else if (action === 'export-pooled') {
        download('pooled-' + base + '.csv',
          (sd.pooledHdr || '') + '\r\n' + (sd.pooledLine || '') + '\r\n', 'text/csv;charset=utf-8');
      } else if (action === 'export-report') {
        download(base + '-report.html', sd.reportHTML || '<p>No report generated.</p>', 'text/html;charset=utf-8');
      } else {
        download(base + '.json', JSON.stringify(rec, null, 2), 'application/json');
      }
    }
    if (action === 'hist-csv' || action === 'hist-json' || action === 'hist-del') {
      var item = el.closest('.hist-item');
      var id = item && item.dataset.id;
      var rec2 = state.history.filter(function (h) { return h.id === id; })[0];
      if (!rec2) return;
      if (action === 'hist-json') {
        download(rec2.code + '-' + rec2.participant + '.json',
          JSON.stringify(rec2, null, 2), 'application/json');
      } else if (action === 'hist-csv') {
        download('pooled-' + rec2.code + '-' + rec2.participant + '.csv',
          (rec2.pooled && rec2.pooled.hdr ? rec2.pooled.hdr + '\r\n' : '') +
          (rec2.pooled && rec2.pooled.line ? rec2.pooled.line + '\r\n' : ''),
          'text/csv;charset=utf-8');
      } else {
        state.history = state.history.filter(function (h) { return h.id !== id; });
        writeStore(HISTORY_KEY, state.history);
        renderHistory();
      }
    }
  }

  function saveFilters() { writeStore('os_studio.filters', state.filters); }

  function init() {
    if (!window.OS_MANIFEST || !window.OS_MANIFEST.length) {
      $('#bootError').hidden = false;
      $$('.view').forEach(function (v) { v.hidden = true; });
      return;
    }

    state.manifest = window.OS_MANIFEST;
    state.history = readStore(HISTORY_KEY, []);
    if (!Array.isArray(state.history)) state.history = [];
    state.filters = Object.assign({ q: '', pack: '', domain: '', license: '', lang: '', sort: 'name' },
                                  readStore('os_studio.filters', {}) || {});
    state.lang = localStorage.getItem(LANG_KEY) || 'en';

    state.languages = (window.OS_BUILD && window.OS_BUILD.languages) ||
      state.manifest.reduce(function (acc, m) {
        m.languages.forEach(function (l) { if (acc.indexOf(l) < 0) acc.push(l); });
        return acc;
      }, []);

    renderStats();
    initTheme();
    initLanguages();
    buildFilters();
    initImport();
    renderLibrary();

    var onSearch = debounce(function (v) {
      state.filters.q = v; refilter();
    }, 180);

    $('#q').addEventListener('input', function (e) { onSearch(e.target.value); });
    $('#fPack').addEventListener('change', function () { state.filters.pack = this.value; refilter(); });
    $('#fDomain').addEventListener('change', function () { state.filters.domain = this.value; refilter(); });
    $('#fLicense').addEventListener('change', function () { state.filters.license = this.value; refilter(); });
    $('#fLang').addEventListener('change', function () { state.filters.lang = this.value; refilter(); });
    $('#fSort').addEventListener('change', function () { state.filters.sort = this.value; refilter(); });
    $('#btnReset').addEventListener('click', resetAll);
    $('#langSelect').addEventListener('change', function () {
      state.lang = this.value;
      localStorage.setItem(LANG_KEY, state.lang);
    });
    $('#btnExportAll').addEventListener('click', exportAllCSV);
    $('#btnClearHistory').addEventListener('click', function () {
      if (!state.history.length) return;
      if (!confirm('Delete all ' + state.history.length + ' recorded sessions?')) return;
      state.history = [];
      writeStore(HISTORY_KEY, state.history);
      renderHistory();
    });

    $('#grid').addEventListener('click', function (e) {
      var cardEl = e.target.closest('.scale-card');
      if (cardEl) setHash('scale', cardEl.dataset.code);
    });

    document.addEventListener('click', delegate);
    window.addEventListener('hashchange', applyRoute);
    applyRoute();
  }

  function resetAll() {
    state.filters = { q: '', pack: '', domain: '', license: '', lang: '', sort: 'name' };
    $('#q').value = ''; $('#fPack').value = ''; $('#fDomain').value = '';
    $('#fLicense').value = ''; $('#fLang').value = ''; $('#fSort').value = 'name';
    state.limit = 150;
    saveFilters(); renderLibrary();
  }

  // Any filter change restarts paging, otherwise "showing 150 of 1095" would
  // silently drop the user back into a stale window.
  function refilter() { state.limit = 150; saveFilters(); renderLibrary(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
