"""Headless interaction checks for sizing, failure recovery and stale-response races.

Uses the real local API, never a model. Delays selected fetch replies to make
navigation and benchmark races deterministic. Writes evidence only to qa/.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import websockets
from review_pages import browser

from fomc.slides import LocalServer

OUT = Path(__file__).resolve().parents[1] / "qa" / "duration_audit"

SETUP = """
window.__uiErrors = [];
addEventListener('error', e => { if (e.error) window.__uiErrors.push(String(e.error)); });
addEventListener('unhandledrejection', e => window.__uiErrors.push(String(e.reason)));
const originalFetch = window.fetch;
window.fetch = async (url, options) => {
  const path = String(url);
  if (path === '/api/duration/scenario' && window.__failDuration)
    return new Response(JSON.stringify({detail:'Temporary test outage'}),
      {status:503, headers:{'Content-Type':'application/json'}});
  const response = await originalFetch(url, options);
  if (path === '/api/backtests') { window.__waitingBacktest = true; await new Promise(r => setTimeout(r, 900)); }
  if (path.includes('/api/backtests/curve?') && path.includes('benchmark=AGG'))
    await new Promise(r => setTimeout(r, 800));
  return response;
};
"""

CHECKS = """(async () => {
  const checks = [];
  const q = selector => document.querySelector(selector);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const check = (condition, label) => { if (!condition) throw Error(label); checks.push(label); };
  const until = async (fn, label) => {
    for (let i=0; i<150; ++i) { if (fn()) return; await sleep(50); }
    throw Error('Timed out: '+label);
  };
  const ready = () => q('#c-duration') && echarts.getInstanceByDom(q('#c-duration'));
  await until(ready, 'initial duration calculation');
  check(q('#nav [data-group="duration"]').classList.contains('active'),
    'duration has its own active sidebar section');
  check(q('.duration-chain') && q('.duration-links a').hash.includes('signal='),
    'stored document links evidence to exposure');
  const ruled = Number(q('[name="duration_change"]').value);
  const budget = q('[name="duration_budget"]'); budget.value = '2';
  budget.dispatchEvent(new Event('input', {bubbles:true}));
  check(Math.abs(Number(q('[name="duration_change"]').value) - 2 * ruled) < 1e-3,
    'a document rule scales with the duration budget, as in the backtest');
  q('#duration-form').requestSubmit(); await until(ready, 'rule at a two-year budget');
  check(!q('#duration-output').textContent.includes('Active duration limit applied'), 'a rule is scaled, not capped');
  check(q('#duration-output').textContent.includes('Round-trip trading cost'), 'cost is a round trip');
  q('#duration-source').value='custom'; q('#duration-source').dispatchEvent(new Event('change',{bubbles:true}));
  await until(ready, 'custom scenario');
  check(q('#duration-output').textContent.includes('$500.00'), 'default dollar DV01');
  check(echarts.getInstanceByDom(q('#c-duration')).getOption().xAxis[0].type === 'value',
    'stress uses proportional numeric shock axis');
  const set = (key, value) => {
    const field = q(`[name="${key}"]`); field.value = value;
    field.dispatchEvent(new Event('input', {bubbles:true}));
  };
  const submit = () => q('#duration-form').requestSubmit();
  set('duration_change', '-3'); set('duration_budget', '0.5');
  check(q('#duration-output').textContent.includes('Inputs changed'), 'edited inputs invalidate stale output');
  submit(); await until(ready, 'capped calculation');
  check(q('#duration-output').textContent.includes('5.50'), 'duration budget applied in UI');
  check(q('#duration-output').textContent.includes('Active duration limit applied'), 'cap disclosed');
  q('[data-theme-choice="dark"]').click(); await until(ready, 'theme recalculation');
  check(q('[name="duration_budget"]').value === '0.5', 'theme change preserves scenario inputs');
  set('duration_budget', '0'); submit(); await until(ready, 'zero budget');
  check(document.querySelectorAll('.duration-legs b')[0].textContent.includes('No trade'), 'zero budget is no trade');
  set('nav_usd', '0');
  check(!q('#duration-form').checkValidity(), 'invalid capital blocked by form');
  set('nav_usd', '1000000'); window.__failDuration = true; submit();
  await until(() => !q('#duration-error').hidden, 'error state');
  check(!q('#c-duration'), 'failure does not retain stale financial output');
  window.__failDuration = false; submit(); await until(ready, 'recovery');
  check(q('#duration-error').hidden, 'calculation recovers after error');
  q('#duration-reset').click(); await until(ready, 'reset example');
  check(q('[name="duration_budget"]').value === '1', 'explicit reset restores example');
  location.hash = '#/backtest';
  await until(() => window.__waitingBacktest, 'delayed backtest fetch');
  location.hash = '#/duration'; await until(ready, 'navigate back to duration');
  await sleep(1100);
  check(q('#duration-form') && q('#view').dataset.page === 'duration',
    'obsolete page cannot overwrite latest navigation');
  location.hash = '#/backtest';
  const btReady = () => {
    const root = q('#c-bt'); return root && echarts.getInstanceByDom(root)?.getOption()?.series?.length;
  };
  await until(btReady, 'backtest curves');
  q('#bt-bench [data-b="AGG"]').click();
  q('#bt-bench [data-b="IEI"]').click();
  await until(() => btReady() && echarts.getInstanceByDom(q('#c-bt')).getOption()
    .series.some(s => s.name === 'IEI alone'), 'IEI selection');
  await sleep(1100);
  const plotted = echarts.getInstanceByDom(q('#c-bt')).getOption().series.map(s => s.name);
  check(plotted.includes('IEI alone') && !plotted.includes('AGG alone'),
    'late AGG response cannot overwrite IEI selection');
  location.hash = '#/backtest?bench=invalid';
  await until(() => q('#bt-bench [data-b=""]')?.classList.contains('on'), 'invalid benchmark reset');
  check(!location.hash.includes('bench=invalid'), 'invalid bookmark normalizes to overlay');
  location.hash='#/fed'; await until(()=>q('.committee-row'), 'compact committee');
  check(!q('.spectrum-track') && !q('.mbio'), 'committee avoids overlapping labels and repeated biographies');
  const voters=document.querySelectorAll('.committee-row').length;
  q('#fed-filter').value='all';q('#fed-filter').dispatchEvent(new Event('change',{bubbles:true}));
  check(document.querySelectorAll('.committee-row').length>=voters, 'committee filter preserves all members');
  location.hash='#/documents';await until(()=>document.querySelectorAll('.document-mini').length===4,'split timeline');
  await until(()=>document.querySelectorAll('.source-badge').length>0,'source badges');
  const quarterly=[...document.querySelectorAll('.document-mini')].map(n=>echarts.getInstanceByDom(n).getOption());
  check(quarterly.every(o=>o.series.some(s=>s.type==='line')), 'timeline starts with separate quarterly summaries');
  q('[data-time-view="documents"]').click();
  check([...document.querySelectorAll('.document-mini')]
    .every(n=>echarts.getInstanceByDom(n).getOption().series[0].type==='scatter'), 'individual document mode retained');
  location.hash='#/pipeline';await until(()=>document.querySelectorAll('.pipeline-item').length===9,'grouped pipeline');
  check(document.querySelectorAll('.pipeline-phase').length===3,'pipeline has three coherent phases');
  check(!document.body.innerText.includes('up to date'),'cached research is not mislabeled live freshness');
  await sleep(500);
  check(window.__uiErrors.length === 0, 'no uncaught browser errors');
  check(document.documentElement.scrollWidth <= innerWidth+1, 'no page overflow at phone width');
  return {checks, browser_errors:window.__uiErrors};
})()"""


async def run(ws_url: str, base: str) -> dict:
    async with websockets.connect(ws_url, max_size=None) as ws:
        seq = 0

        async def call(method, **params):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({"id": seq, "method": method, "params": params}))
            while True:
                message = json.loads(await ws.recv())
                if message.get("id") == seq:
                    if "error" in message:
                        raise RuntimeError(message["error"])
                    return message.get("result", {})

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Emulation.setDeviceMetricsOverride", width=390, height=1000, deviceScaleFactor=1, mobile=True)
        await call("Page.addScriptToEvaluateOnNewDocument", source=SETUP)
        await call("Page.navigate", url=base + "/?theme=light#/duration")
        # Wait for the document's own script, not a fixed page-load guess.
        for _ in range(100):
            state = await call("Runtime.evaluate", expression="Boolean(document.querySelector('#duration-form'))")
            if state.get("result", {}).get("value"):
                break
            await asyncio.sleep(0.1)
        result = await call("Runtime.evaluate", expression=CHECKS, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"]["value"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with LocalServer() as srv:
        proc, profile, socket = browser()
        try:
            result = asyncio.run(run(socket, srv.base))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            shutil.rmtree(profile, ignore_errors=True)
    (OUT / "interactions.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
