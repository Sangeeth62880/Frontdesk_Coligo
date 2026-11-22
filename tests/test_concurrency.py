from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import psycopg
import pytest
from fastapi.testclient import TestClient

from frontdesk import service
from tests.conftest import login_headers
from tests.test_mutations import create, event_types
from tests.test_sweep import SWEEP, threshold, wait


def parallel(client, actions):
    barrier=Barrier(len(actions))
    def run(action):
        with TestClient(client.app) as c:
            barrier.wait(timeout=10)
            return action(c)
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run,actions))


def test_n_claims_one_event(harness,agent_headers):
    c,_url,_=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    credentials={i:login_headers(c,i) for i in range(1,10)}
    results=parallel(c,[lambda c,i=i:c.post(p+'/claim',headers=credentials[i]) for i in range(1,10)])
    assert sorted(r.status_code for r in results)==[200]+[409]*8
    assert len([e for e in event_types(c,t['id'],agent_headers) if e['event_type']=='claimed'])==1
    winner=next(r.json()['assignee_id'] for r in results if r.status_code==200)
    assert c.post(p+'/claim',headers=credentials[winner]).status_code==200
    assert len(event_types(c,t['id'],agent_headers))==2


def test_stale_simultaneous_status_conflict(harness,agent_headers):
    c,_,_=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    c.post(p+'/claim',headers=agent_headers)
    version=c.get(p,headers=agent_headers).json()['version']
    results=parallel(c,[lambda c:c.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':version}),lambda c:c.post(p+'/status',headers=agent_headers,json={'status':'waiting_on_customer','body':'Question','version':version})])
    assert sorted(r.status_code for r in results)==[200,409]
    assert len([e for e in event_types(c,t['id'],agent_headers) if e['event_type']=='status_changed'])==1
    assert c.post(p+'/status',headers=agent_headers,json={'status':'open'}).status_code==422

@pytest.mark.parametrize('customer',[False,True])
def test_parallel_idempotent_reply_and_expiration(harness,agent_headers,customer):
    c,url,_=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    c.post(p+'/claim',headers=agent_headers)
    hdr=({'X-Customer-Token':t['customer_token']} if customer else agent_headers)|{'Idempotency-Key':'double-submit'}
    route=p+('/customer-reply' if customer else '/messages')
    results=parallel(c,[lambda c:c.post(route,headers=hdr,json={'body':'One reply'})]*2)
    assert [r.status_code for r in results]==[201,201]
    assert results[0].json()==results[1].json()
    assert c.post(route,headers=hdr,json={'body':'Different'}).status_code==409
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM public_messages').fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM events WHERE event_type='public_reply'").fetchone()[0]==1
        db.execute("UPDATE request_idempotency SET created_at=clock_timestamp()-interval '25 hours'")
    result=c.post(route,headers=hdr,json={'body':'One reply'})
    assert result.status_code==201 and result.json()['id']!=results[0].json()['id']

@pytest.mark.parametrize('first',['reply','close'])
def test_reply_close_race_both_lock_orders(harness,agent_headers,monkeypatch,first):
    c,url,now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    wait(c,t,agent_headers);now[0]=threshold(url,now[0])
    held=Event();release=Event()
    # Hold the real DB transaction after it has acquired its row lock.
    original=service.public_message if first=='reply' else service.resume
    def hold(*args,**kwargs):
        held.set()
        assert release.wait(timeout=10)
        return original(*args,**kwargs)
    monkeypatch.setattr(service,'public_message' if first=='reply' else 'resume',hold)
    def reply():
        with TestClient(c.app) as other:
            return other.post(p+'/customer-reply',headers={'X-Customer-Token':t['customer_token']},json={'body':'Never lost'})
    def sweep():
        with TestClient(c.app) as other:return other.post('/admin/sweep',headers=SWEEP)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(reply if first=='reply' else sweep)
        assert held.wait(timeout=10)
        b=pool.submit(sweep if first=='reply' else reply)
        try:
            if first=='reply':
                # SKIP LOCKED makes the losing sweep an immediate no-op.
                assert b.result(timeout=10).json()['closed_count']==0
        finally:release.set()
        ra=a.result(timeout=10);rb=b.result(timeout=10)
    reply_result=ra if first=='reply' else rb
    assert reply_result.status_code==201
    view=c.get(p,headers=agent_headers).json()
    assert view['status']==('open' if first=='reply' else 'closed')
    new_id=reply_result.json()['ticket_id']
    assert (new_id==t['id']) == (first=='reply')
    with psycopg.connect(url) as db:
        assert db.execute("SELECT count(*) FROM public_messages WHERE body='Never lost'").fetchone()[0]==1
        if first=='close':
            assert db.execute('SELECT previous_ticket_id FROM tickets WHERE id=%s',(new_id,)).fetchone()[0]==t['id']
    assert c.post('/admin/sweep',headers=SWEEP).json()['closed_count']==0
    assert c.post(p+'/notes',headers=agent_headers,json={'body':'No edit'}).status_code==(201 if first=='reply' else 409)


def test_only_uninterrupted_wait_autocloses(harness,agent_headers):
    c,url,now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    wait(c,t,agent_headers)
    old_start=now[0];now[0]=threshold(url,old_start)-timedelta(minutes=1)
    c.post(p+'/customer-reply',headers={'X-Customer-Token':t['customer_token']},json={'body':'Reset interval'})
    wait(c,t,agent_headers)
    new_start=now[0];now[0]=threshold(url,old_start)
    assert c.post('/admin/sweep',headers=SWEEP).json()['closed_count']==0
    now[0]=threshold(url,new_start)
    assert c.post('/admin/sweep',headers=SWEEP).json()['closed_count']==1
