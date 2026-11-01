"""Harvest user-visible English strings, excluding scale content.

Scale text is translated separately (data/translate.sqlite3). This walks the
rendered shell only: chrome containers, buttons, placeholders and labels —
never anything inside a scale card, detail body, option list or score readout.
"""
import http.server, json, socketserver, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path("/workspace/openscales-studio"); PORT=8921
BASE=f"http://127.0.0.1:{PORT}/index.html"
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
socketserver.TCPServer.allow_reuse_address=True
srv=socketserver.TCPServer(("127.0.0.1",PORT), lambda *a,**k: Q(*a,directory=str(ROOT),**k))
threading.Thread(target=srv.serve_forever,daemon=True).start()

CHROME = "#nav,.topbar,.hero,.stats,.toolbar,#emptyState,.run-head,#historyList,#dropzone,.footer,#bootError,.actions,.more,#resultCard .result-head,#resultCard button,#resultCard .export-row"

HARVEST = """(sel) => {
  const out=[];
  const isScaleData = el => el.closest('.scale-card,.detail-body,.dim-list,#historyList .hist-card,.gauge-labels,.sr-main,.sr-question,.sr-likert-row,.score-box,.citation');
  document.querySelectorAll(sel).forEach(root => {
    root.querySelectorAll('*').forEach(el => {
      if (typeof el.className === 'string' && el.className.includes('sr-')) {
        // runner chrome (buttons, headings) is UI; questions are handled above
      }
      const own = Array.from(el.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ').trim();
      if (own && !isScaleData(el)) out.push({text:own, kind:'text', tag:el.tagName+'.'+(typeof el.className==='string'?el.className.slice(0,30):'')});
      ['placeholder','aria-label','title'].forEach(a => {
        const v = el.getAttribute && el.getAttribute(a);
        if (v) out.push({text:v, kind:a, tag:el.tagName});
      });
    });
  });
  // runner buttons live outside the chrome selector
  document.querySelectorAll('#runnerHost button, .sr-nav button, .sr-next-btn, .sr-back-btn').forEach(b => {
    const t=b.textContent.trim(); if(t) out.push({text:t, kind:'button', tag:b.className});
  });
  return out;
}"""

def answer(page, n=5, idx=0):
    for _ in range(n):
        page.wait_for_timeout(110)
        if page.query_selector(".sr-debrief-heading, .sr-terminate-heading"): return
        o=page.query_selector_all(".sr-likert-btn, .sr-option-btn")
        if o: o[min(idx,len(o)-1)].click()
        page.wait_for_timeout(70)
        n=page.query_selector(".sr-next-btn")
        if n and n.is_enabled(): n.click()

found=[]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/usr/bin/chromium",args=["--no-sandbox"])
    pg=b.new_page()
    def grab(label):
        for r in pg.evaluate(HARVEST, CHROME):
            r['view']=label; found.append(r)
    pg.goto(BASE, wait_until="domcontentloaded"); pg.wait_for_selector(".scale-card"); grab("library")
    pg.click('[data-action="more"]'); pg.wait_for_timeout(300); grab("library-more")
    pg.goto(BASE+"#/scale/PHQ9", wait_until="domcontentloaded"); pg.wait_for_selector("#view-detail h2"); pg.wait_for_timeout(400); grab("detail")
    pg.goto(BASE+"#/history", wait_until="domcontentloaded"); pg.wait_for_timeout(300); grab("history-empty")
    pg.goto(BASE+"#/import", wait_until="domcontentloaded"); pg.wait_for_timeout(300); grab("import")
    pg.goto(BASE+"#/run/PHQ9", wait_until="domcontentloaded")
    pg.wait_for_selector(".sr-next-btn, .sr-likert-btn", timeout=20000); grab("run")
    answer(pg,3); grab("run-mid")
    for _ in range(40):
        pg.wait_for_timeout(110)
        if pg.query_selector(".sr-debrief-heading, .sr-terminate-heading"): break
        o=pg.query_selector_all(".sr-likert-btn")
        if o: o[2].click()
        pg.wait_for_timeout(70); n=pg.query_selector(".sr-next-btn")
        if n and n.is_enabled(): n.click()
    pg.wait_for_selector("#resultCard:not([hidden])", timeout=15000); grab("result")
    pg.goto(BASE+"#/history", wait_until="domcontentloaded"); pg.wait_for_selector(".hist-item", timeout=8000); grab("history")
    b.close()

uniq={}
for r in found:
    k=r['text'].strip()
    if k and k not in uniq: uniq[k]=r
english=[v for v in uniq.values() if any(c.isalpha() for c in v['text']) and not any('一'<=c<='鿿' for c in v['text'])]
print(f"界面文案 {len(english)} 条")
Path("/tmp/ui_chrome.json").write_text(json.dumps(english, indent=1, ensure_ascii=False), encoding="utf-8")
for r in english: print(f"  [{r['view']:12}] {r['kind']:12} {r['text'][:88]}")
