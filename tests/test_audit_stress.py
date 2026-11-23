"""Seeded parallel histories replay their business state from immutable events."""
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from tests.test_concurrency import parallel


def assert_replay(db, ticket_id):
    state={'status':'open','assignee_id':None,'cycle_number':1,'first_replied_at':None,'previous_ticket_id':None}
    messages=[]
    notes=[]
    open_pauses=set()
    for event in db.execute('SELECT * FROM events WHERE ticket_id=%s ORDER BY id',(ticket_id,)):
        kind=event['event_type']; after=event['after_value'] or {}
        if kind=='created':
            if after.get('message_id') is not None:messages.append(after['message_id'])
            state['priority']=after['priority']
            state['previous_ticket_id']=after['previous_ticket_id']
        if kind in ('claimed','reassigned'):state['assignee_id']=after['assignee_id']
        if kind in ('status_changed','auto_closed','reopened'):state['status']=after['status']
        if kind=='priority_changed':state['priority']=after['priority']
        if 'cycle_number' in after:state['cycle_number']=after['cycle_number']
        if kind=='public_reply':
            messages.append(after['message_id'])
            if after['first_replied_at']:
                state['first_replied_at']=datetime.fromisoformat(after['first_replied_at'])
        if kind=='internal_note_added':notes.append(after['note_id'])
        if kind=='paused':open_pauses.add(after['pause_id'])
        if kind=='resumed':open_pauses.remove(after['pause_id'])
    row=db.execute('SELECT * FROM tickets WHERE id=%s',(ticket_id,)).fetchone()
    for field,expected in state.items():
        if field=='cycle_number':
            actual=db.execute('SELECT max(cycle_number) AS n FROM resolution_cycles WHERE ticket_id=%s',(ticket_id,)).fetchone()['n']
        else:actual=row[field]
        assert actual==expected,(ticket_id,field,actual,expected)
    for table,ids in [('public_messages',messages),('internal_notes',notes)]:
        assert len(ids)==len(set(ids))
        assert sorted(ids)==[r['id'] for r in db.execute(f'SELECT id FROM {table} WHERE ticket_id=%s ORDER BY id',(ticket_id,))]
    assert open_pauses=={r['id'] for r in db.execute('SELECT id FROM ticket_pauses WHERE ticket_id=%s AND resumed_at IS NULL',(ticket_id,))}


def test_parallel_creation_mixed_mutations_and_event_replay(harness,agent_headers):
    c,url,_=harness
    def create_one(i):
        with TestClient(c.app) as client:
            r=client.post('/tickets',headers=agent_headers,json={'body':'Test description', 'subject':f'Seeded stress {i}','customer_email':'stress@example.com'})
            assert r.status_code==201
            return r.json()
    with ThreadPoolExecutor(max_workers=10) as pool:
        tickets=list(pool.map(create_one,range(30)))
    ids=sorted(t['id'] for t in tickets)
    assert len(set(ids))==30
    assert ids==list(range(ids[0],ids[0]+30))
    rng=random.Random(20261122)
    rng.shuffle(tickets)
    for i,t in enumerate(tickets):
        p=f'/tickets/{t["id"]}'
        if i%3==0:
            version=c.get(p,headers=agent_headers).json()['version']
            actions=[lambda client,p=p:client.post(p+'/claim',headers=agent_headers),lambda client,p=p,v=version:client.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':v})]
        else:
            assert c.post(p+'/claim',headers=agent_headers).status_code==200
            version=c.get(p,headers=agent_headers).json()['version']
            if i%3==1:
                actions=[lambda client,p=p:client.post(p+'/priority',headers=agent_headers,json={'priority':'urgent'}),lambda client,p=p:client.post(p+'/messages',headers=agent_headers,json={'body':'Concurrent answer'})]
            else:
                actions=[lambda client,p=p,v=version:client.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':v}),lambda client,p=p,t=t:client.post(p+'/customer-reply',headers={'X-Customer-Token':t['customer_token']},json={'body':'Concurrent customer'})]
        results=parallel(c,actions)
        assert all(r.status_code in (200,201,409) for r in results),[r.text for r in results]
    for t in tickets:
        p=f'/tickets/{t["id"]}'
        if c.get(p,headers=agent_headers).json()['status']=='resolved':
            results=parallel(c,[lambda client,p=p:client.post(p+'/agent-reopen',headers=agent_headers),lambda client:client.post('/admin/sweep',headers={'Authorization':'Bearer test-sweep-secret'})])
            assert all(r.status_code==200 for r in results)
    with psycopg.connect(url,row_factory=dict_row) as db:
        for tid in ids:assert_replay(db,tid)


def test_double_logout_has_no_server_error(harness,agent_headers):
    c,_,_=harness
    results=parallel(c,[lambda client:client.post('/auth/logout',headers=agent_headers)]*2)
    assert all(r.status_code in (200,401) for r in results)
    assert c.get('/auth/me',headers=agent_headers).status_code==401


def test_six_deterministic_review_cases_preserve_immutable_history(harness):
    from scripts.seed_review_demo import seed_review
    _c,url,now=harness
    with psycopg.connect(url,row_factory=dict_row) as db:
        first=seed_review(db,now[0])
        events=db.execute('SELECT * FROM events ORDER BY id').fetchall()
        assert len(first)==6 and seed_review(db,now[0])==first
        assert db.execute('SELECT * FROM events ORDER BY id').fetchall()==events
        rows=db.execute('SELECT * FROM tickets ORDER BY id').fetchall()
        assert {'urgent','medium','small'}=={r['priority'] for r in rows}
        assert sum(r['assignee_id'] is None for r in rows)==2
        assert {r['status'] for r in rows}=={'open','waiting_on_customer','resolved'}
        for tid in first:assert_replay(db,tid)


def test_list_sla_prefetch_has_constant_query_count(harness,agent_headers,monkeypatch):
    c,_,_=harness
    for i in range(25):
        assert c.post('/tickets',headers=agent_headers,json={'body':'Test description', 'subject':f'Prefetch {i}','customer_email':'prefetch@example.com','source':'agent'}).status_code==201
    assert c.get('/tickets?assignee=all',headers=agent_headers).status_code==200
    statements=[]
    execute=psycopg.Connection.execute
    def traced(self,query,*args,**kwargs):
        statements.append(str(query))
        return execute(self,query,*args,**kwargs)
    monkeypatch.setattr(psycopg.Connection,'execute',traced)
    r=c.get('/tickets?assignee=all',headers=agent_headers)
    assert r.status_code==200 and len(r.json())==25
    assert len(statements)<=8,statements
    assert not any(statement.startswith('UPDATE') for statement in statements)


def test_shutdown_during_active_sweep_commits_once_and_joins(api_db,monkeypatch):
    from datetime import timedelta
    from threading import Event

    from frontdesk import service
    from frontdesk.business_time import ZONE
    from frontdesk.events import log_event
    from frontdesk.scheduler import Sweeper
    old=datetime(2026,11,2,10,tzinfo=ZONE)
    with psycopg.connect(api_db,row_factory=dict_row) as db:
        t=service.create_ticket(db,'Shutdown sweep regression','shutdown@example.com','small',old,'customer')
        t=db.execute('UPDATE tickets SET assignee_id=1 WHERE id=%s RETURNING *',(t['id'],)).fetchone()
        log_event(db,t['id'],'agent:1','claimed',before={'assignee_id':None},after={'assignee_id':1})
        service.public_message(db,t,'Please supply details.',old+timedelta(minutes=10),'agent:1',1)
        service.change_status(db,service.locked_ticket(db,t['id']),'waiting_on_customer',old+timedelta(minutes=10),'agent:1')
    held,release=Event(),Event()
    original=service.resume
    def held_resume(*args,**kwargs):
        held.set()
        assert release.wait(timeout=10)
        return original(*args,**kwargs)
    monkeypatch.setattr(service,'resume',held_resume)
    sweeper=Sweeper(api_db,60)
    sweeper.start()
    try:
        assert held.wait(timeout=5)
        with ThreadPoolExecutor(max_workers=1) as pool:
            stopped=pool.submit(sweeper.stop)
            assert sweeper.stop_event.wait(timeout=5)
            assert not stopped.done()
            release.set()
            stopped.result(timeout=10)
    finally:
        release.set()
        sweeper.stop()
    assert not sweeper.thread.is_alive()
    with psycopg.connect(api_db,row_factory=dict_row) as db:
        assert db.execute('SELECT status FROM tickets').fetchone()['status']=='closed'
        assert db.execute("SELECT count(*) AS n FROM events WHERE event_type='auto_closed'").fetchone()['n']==1
        assert_replay(db,t['id'])
