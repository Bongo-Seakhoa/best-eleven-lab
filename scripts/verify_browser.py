"""Optional UI smoke test. Requires Playwright and a Chromium executable."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import tempfile
import time
import json
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, Error as BrowserError

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--chromium',default=None,help='Optional system Chromium path')
parser.add_argument('--preview',default=str(ROOT/'BEST_ELEVEN_PREVIEW.html'))
args=parser.parse_args()
report={'browser_errors':[],'checks':[],'provenance':'Synthetic UI verification; not real-data validation'}
env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
with tempfile.TemporaryDirectory(prefix='best-eleven-ui-') as temporary:
    database=Path(temporary)/'demo.sqlite'
    subprocess.run([sys.executable,'-m','best_eleven','--db',str(database),'demo'],cwd=ROOT,env=env,check=True,capture_output=True)
    log=(Path(temporary)/'server.log').open('w')
    process=subprocess.Popen([sys.executable,'-m','best_eleven','--db',str(database),'serve','--port','18765'],cwd=ROOT,env=env,stdout=log,stderr=log)
    try:
        for _ in range(60):
            try:
                with urlopen('http://127.0.0.1:18765/api/status',timeout=1) as r:
                    if r.status==200:break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Local app did not become ready')
        with sync_playwright() as p:
            options={'headless':True}
            if args.chromium:options['executable_path']=args.chromium
            browser=p.chromium.launch(**options)
            page=browser.new_page(viewport={'width':1440,'height':1100})
            page.on('pageerror',lambda e:report['browser_errors'].append(str(e)))
            try:
                page.goto('http://127.0.0.1:18765/',wait_until='networkidle')
                assert page.locator('.xi-row').count()==0
                report['checks'].append('Real view starts empty; no automatic synthetic substitution')
                page.locator('#dataset').select_option('demo')
                page.wait_for_selector('.xi-row')
                assert page.locator('.xi-row').count()==11
                report['checks'].append('Live local API builds eleven fictional Test players')
                page.locator('#experience').fill('40');page.locator('#performance').fill('60');page.locator('#analyse').click()
                page.wait_for_selector('.xi-row')
                assert page.locator('.xi-row').count()==11
                report['checks'].append('Arbitrary live preference change recomputes a valid XI')
                page.locator('.xi-row .player-button').first.click()
                page.wait_for_selector('#profileBody:not([hidden])')
                assert page.locator('#spatialReason').inner_text().startswith('Standard Cricsheet')
                page.locator('[data-discipline=bowling]').click()
                page.locator('#split').select_option('archetypes')
                report['checks'].append('Player API, bowling archetype switch and spatial guard render')
                page.locator('#whyNot').click()
                page.wait_for_selector('#whyNotResult:not([hidden])')
                assert 'not a prediction' in page.locator('#whyNotResult').inner_text()
                report['checks'].append('Reoptimized inclusion comparison renders as utility, not predicted runs')
                page.locator('[data-tab=selection]').click()
                page.locator('#scopeDetails summary').click()
                page.locator('#minPace').fill('11');page.locator('#analyse').click()
                page.wait_for_function("document.querySelector('#selectionCount').textContent.startsWith('0')")
                assert page.locator('.xi-row').count()==0
                report['checks'].append('Infeasible constraints return no XI instead of a silently relaxed team')
                page.locator('#minPace').fill('0');page.locator('#analyse').click();page.wait_for_selector('.xi-row')
                page.locator('[data-tab=data]').click()
                page.locator('#importZip').set_input_files({'name':'invalid.zip','mimeType':'application/zip','buffer':b'not a zip'})
                page.wait_for_function("document.querySelector('#status').classList.contains('error')")
                assert 'not a ZIP' in page.locator('#status').inner_text()
                report['checks'].append('Invalid archive is rejected visibly through the browser upload route')
                page.locator('[data-tab=methods]').click();assert page.locator('.method-title').is_visible()
            except BrowserError as error:
                if 'ERR_BLOCKED_BY_ADMINISTRATOR' not in str(error):
                    raise
                report['live_browser_status']='blocked_by_environment_navigation_policy'
                report['live_browser_note']='Local HTTP health check succeeded; full browser-to-server navigation was blocked. API behavior is separately tested with FastAPI TestClient.'
            else:
                report['live_browser_status']='passed'
            browser.close()
            browser=p.chromium.launch(**options)
            page=browser.new_page(viewport={'width':1440,'height':1100})
            page.on('pageerror',lambda e:report['browser_errors'].append(str(e)))
            # Loading the self-contained HTML into a page avoids environment-specific file:// restrictions.
            page.set_content(Path(args.preview).read_text(encoding='utf-8'),wait_until='load')
            assert page.locator('.xi-row').count()==11
            page.screenshot(path=str(ROOT/'docs/selection-preview.png'),full_page=True)
            page.locator('.xi-row .player-button').first.click()
            page.screenshot(path=str(ROOT/'docs/player-preview.png'),full_page=True)
            page.locator('[data-tab=selection]').click()
            page.set_viewport_size({'width':390,'height':844})
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(ROOT/'docs/mobile-preview.png'),full_page=True)
            for fmt in ['ODI','T20','Test']:
                page.locator(f'[data-format={fmt}]').click()
                assert page.locator('.xi-row').count()==11
            page.locator('#preset').select_option('40')
            assert page.locator('.xi-row').count()==11
            page.locator('#sensitivity').click();assert page.locator('#sensitivityResults h4').is_visible()
            assert page.locator('#fetch').is_disabled()
            report['checks'].append('Offline preview: three formats, saved scenarios, sensitivity and disabled live-only actions')
            report['checks'].append('390-pixel mobile viewport has no document-level horizontal overflow')
            assert not report['browser_errors']
            browser.close()
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()
report['status']='partial' if report.get('live_browser_status')!='passed' else 'passed'
report['offline_browser_status']='passed'
(ROOT/'examples/browser_verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
if report['status']=='partial':
    raise SystemExit(2)
