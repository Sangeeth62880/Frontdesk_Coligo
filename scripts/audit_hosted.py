"""Read-mostly hosted verification; paced load and explicitly labeled synthetic tickets.

Run: uv run python -m scripts.audit_hosted [--load] [--browser]
Demo credentials are read from the enabled demo hint into memory, never output.
Synthetic ticket IDs are retained as intentional audit records; no event mutations.
"""
import argparse
import html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

BASE='https://frontdesk-spfe.onrender.com'
OUT=Path(os.environ.get('FRONTDESK_AUDIT_OUTPUT', 'output/audit'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--load',action='store_true')
    parser.add_argument('--browser',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    page=session.get(BASE,timeout=120)
    match=re.search(r'Password: ([^<]*)</p>',page.text)
    password=os.environ.get('FRONTDESK_DEMO_PASSWORD') or (html.unescape(match.group(1)) if match else None)
    if not password:raise RuntimeError('Supply FRONTDESK_DEMO_PASSWORD securely when the demo hint is disabled')
    response=session.post(BASE+'/auth/login',json={'email':'meera@arvo.example','password':password},timeout=30)
    if response.status_code!=200:raise RuntimeError(f'Hosted sign-in returned {response.status_code}')
    token=response.json()['token']
    headers={'Authorization':'Bearer '+token}
    result: dict[str, Any]={'base':BASE,'utc_started':datetime.now(UTC).isoformat(),'synthetic_tickets':[]}
    try:
        listing=session.get(BASE+'/tickets?assignee=all',headers=headers,timeout=30)
        assert listing.status_code==200
        tickets=listing.json()
        result['read_ticket_count']=len(tickets)
        result['agent_no_store']=listing.headers.get('Cache-Control')=='private, no-store'
        result['legacy_agent_list_exposes_capabilities']=any('customer_token' in t for t in tickets)
        if args.browser:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser=p.chromium.launch()
                context=browser.new_context(accept_downloads=True)
                browser_page=context.new_page()
                errors=[]
                browser_page.on('pageerror',lambda e:errors.append(str(e)))
                browser_page.goto(BASE)
                browser_page.locator('#login-email').fill('meera@arvo.example')
                browser_page.locator('#login-password').fill(password)
                browser_page.get_by_role('button',name='Sign in',exact=True).click()
                browser_page.locator('#login-dialog').wait_for(state='hidden')
                browser_page.locator('[data-queue=all]').click()
                browser_page.locator('#status-filter').select_option('all')
                browser_page.locator('#ticket-list .ticket-row').first.wait_for()
                source=Path('node_modules/axe-core/axe.min.js').read_text()
                browser_page.evaluate(source)
                violations=browser_page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))")
                result['browser']={'js_errors':errors,'axe_list':violations,'overflow':{}}
                for width in (390,768,1280):
                    browser_page.set_viewport_size({'width':width,'height':900})
                    result['browser']['overflow'][width]=browser_page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    screens=Path('output/screens');screens.mkdir(exist_ok=True,parents=True)
                    browser_page.screenshot(path=str(screens/f'hosted-list-{width}.png'),full_page=True)
                browser_page.get_by_label('Workspace menu').click()
                browser_page.locator('#signout').click()
                browser_page.locator('#login-dialog').wait_for(state='visible')
                browser.close()
        if args.load:
            # 50 virtual users, a global ceiling of 5 reads/sec, for 60 seconds.
            # Read caps are conservative for a free-tier database with no pool.
            lock=threading.Lock();next_request=[time.monotonic()]
            start=time.monotonic();end=start+60
            latencies=[];statuses=[]
            def read_user(i):
                local=[]
                with requests.Session() as client:
                    while True:
                        with lock:
                            slot=max(time.monotonic(),next_request[0])
                            next_request[0]=slot+.2
                        if slot>=end:break
                        time.sleep(max(0,slot-time.monotonic()))
                        path='/tickets?assignee=all' if i%2==0 or not tickets else f'/tickets/{tickets[i%len(tickets)]["id"]}'
                        tick=time.monotonic()
                        try:r=client.get(BASE+path,headers=headers,timeout=20);status=r.status_code
                        except requests.RequestException:status=0
                        local.append((time.monotonic()-tick,status))
                return local
            with ThreadPoolExecutor(max_workers=50) as pool:
                for rows in pool.map(read_user,range(50)):
                    for latency,status in rows:latencies.append(latency);statuses.append(status)
            ordered=sorted(latencies)
            result['read_load']={'virtual_users':50,'duration_seconds':round(time.monotonic()-start,3),'global_max_rps':5,'requests':len(statuses),'p95_seconds':round(ordered[int(.95*(len(ordered)-1))],3),'errors':sum(s!=200 for s in statuses),'status_counts':{str(s):statuses.count(s) for s in set(statuses)}}
            # Ten concurrent writers each create one labeled ticket. No unbounded writes.
            def write_user(i):
                tick=time.monotonic()
                try:
                    r=requests.post(BASE+'/tickets',headers=headers,json={'body':'Test description', 'subject':f'Hosted verification: release load {result["utc_started"]} #{i+1:02d}','customer_email':'hosted-verification@arvo.example','priority':'small','source':'agent'},timeout=30)
                    return {'status':r.status_code,'id':r.json().get('id'),'seconds':round(time.monotonic()-tick,3)}
                except requests.RequestException:return {'status':0,'id':None,'seconds':round(time.monotonic()-tick,3)}
            with ThreadPoolExecutor(max_workers=10) as pool:writes=list(pool.map(write_user,range(10)))
            result['writer_load']={'users':10,'operations':'one create each','results':writes,'errors':sum(r['status']!=201 for r in writes),'p95_seconds':max(r['seconds'] for r in writes)}
            result['synthetic_tickets']=[r['id'] for r in writes if r['id'] is not None]
            result['cleanup']='Left clearly labeled tickets and their append-only history; no deletions, renames or event rewrites.'
        print(json.dumps(result,indent=2))
        (OUT/'hosted-verification.json').write_text(json.dumps(result,indent=2))
    finally:
        session.post(BASE+'/auth/logout',headers=headers,timeout=30)


if __name__=='__main__':main()
