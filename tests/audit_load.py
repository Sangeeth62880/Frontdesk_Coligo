"""Explicit paced local load command; not part of routine unit-suite collection.
Run: uv run --env-file .env pytest tests/audit_load.py -q -s
Set TEST_DATABASE_URL explicitly to a local schema-capable PostgreSQL database.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from tests.conftest import TEST_PASSWORD
from tests.test_audit_browser import browser_stack as browser_stack  # noqa: PLC0414 - register pytest fixture


def test_local_50_readers_10_writers(browser_stack):
    base,_,_=browser_stack
    login=requests.post(base+'/auth/login',json={'email':'meera@arvo.example','password':TEST_PASSWORD},timeout=10)
    assert login.status_code==200
    headers={'Authorization':'Bearer '+login.json()['token']}
    ids=[]
    for i in range(18):
        r=requests.post(base+'/tickets',headers=headers,json={'subject':f'Local audit load {i}','customer_email':'load@example.com','source':'agent'},timeout=10)
        assert r.status_code==201
        ids.append(r.json()['id'])
    # Warm materialized breach flags; subsequent unchanged reads need no updates.
    assert requests.get(base+'/tickets?assignee=all',headers=headers,timeout=10).status_code==200
    lock=threading.Lock();next_request=[time.monotonic()]
    start=time.monotonic();end=start+60
    def read_user(i):
        result=[]
        with requests.Session() as client:
            while True:
                with lock:
                    slot=max(time.monotonic(),next_request[0]);next_request[0]=slot+.2
                if slot>=end:break
                time.sleep(max(0,slot-time.monotonic()))
                tick=time.monotonic()
                path='/tickets?assignee=all' if i%2==0 else f'/tickets/{ids[i%len(ids)]}'
                try:r=client.get(base+path,headers=headers,timeout=20);status=r.status_code
                except requests.RequestException:status=0
                result.append((time.monotonic()-tick,status))
        return result
    with ThreadPoolExecutor(max_workers=50) as pool:
        results=[item for batch in pool.map(read_user,range(50)) for item in batch]
    elapsed=time.monotonic()-start
    def write_user(i):
        tick=time.monotonic()
        r=requests.post(base+'/tickets',headers=headers,json={'subject':f'Local concurrent writer {i}','customer_email':'load@example.com'},timeout=20)
        return time.monotonic()-tick,r.status_code
    with ThreadPoolExecutor(max_workers=10) as pool:writes=list(pool.map(write_user,range(10)))
    latencies=sorted(r[0] for r in results)
    summary={'base':'isolated local stack','seed_tickets':18,'read_virtual_users':50,'read_global_max_rps':5,'read_schedule_seconds':60,'elapsed_including_drain':round(elapsed,3),'read_requests':len(results),'read_p95_seconds':round(latencies[int(.95*(len(latencies)-1))],4),'read_errors':sum(r[1]!=200 for r in results),'concurrent_writers':10,'write_p95_seconds':round(max(r[0] for r in writes),4),'write_errors':sum(r[1]!=201 for r in writes)}
    Path('output/audit/local-load.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))
    assert summary['read_errors']==0 and summary['write_errors']==0
