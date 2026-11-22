from tests.conftest import login_headers
"""One deterministic, freshly migrated PostgreSQL scenario for the ticket lifecycle."""
from datetime import datetime, timedelta
import json
import psycopg
import pytest
from tests.test_business_time import at
from tests.test_concurrency import parallel
from tests.test_mutations import create, event_types
from tests.test_security_hardening import rendered_ui, Tags
from tests.test_sweep import wait, threshold, SWEEP


def test_frontdesk_end_to_end(harness,agent_headers):
    c,url,now=harness
    agents=c.get('/agents',headers=agent_headers).json()
    assert [(a['id'],a['name']) for a in agents[:2]]==[(1,'Meera'),(2,'Arun')]
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM tickets').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM holidays').fetchone()[0]>22
        assert db.execute('SELECT count(*) FROM sla_policies').fetchone()[0]==3

    now[0]=at('2026-11-20T17:50')
    urgent=create(c,agent_headers,'urgent');p=f'/tickets/{urgent["id"]}'
    customer={'X-Customer-Token':urgent['customer_token']}
    assert datetime.fromisoformat(urgent['start_at'])==now[0]
    view=c.get(p,headers=agent_headers).json()
    assert datetime.fromisoformat(view['sla']['resolution_due_at'])==at('2026-11-20T18:30')
    # 120 - 40 Friday minutes = 80 Monday minutes; 09:30 + 80 = 10:50.
    assert datetime.fromisoformat(view['sla']['first_reply_due_at'])==at('2026-11-23T10:50')

    credentials={i:login_headers(c,i) for i in [1,2]}
    claims=parallel(c,[lambda c,i=i:c.post(p+'/claim',headers=credentials[i]) for i in [1,2]])
    assert sorted(r.status_code for r in claims)==[200,409]
    winner=next(r.json()['assignee_id'] for r in claims if r.status_code==200)
    loser=next(r for r in claims if r.status_code==409)
    assert loser.json()['detail']['assignee_name']==agents[winner-1]['name']
    owner=credentials[winner]

    now[0]+=timedelta(minutes=1)
    assert c.post(p+'/notes',headers=owner,json={'body':'NOTE_MARKER_7f3a'}).status_code==201
    assert c.get(p,headers=owner).json()['first_reply_at'] is None
    now[0]+=timedelta(minutes=1);reply_time=now[0]
    raw='<script>alert("xss")</script>'
    assert c.post(p+'/messages',headers={**owner,'Idempotency-Key':'e2e-public'},json={'body':raw}).status_code==201
    view=c.get(p,headers=owner).json()
    assert datetime.fromisoformat(view['first_reply_at'])==reply_time
    assert view['first_reply_actor']==f'agent:{winner}'
    for route in ['/customer/tickets',f'/customer/tickets/{urgent["id"]}','/export.csv','/customer','/search?q=invoice']:
        r=c.get(route,headers=customer)
        assert 'NOTE_MARKER' not in r.text+str(r.headers)
    assert 'NOTE_MARKER' not in json.dumps(event_types(c,urgent['id'],owner))
    for route in ['/tickets',p,p+'/events','/agents']:
        assert c.get(route,headers=customer).status_code==401

    now[0]=at('2026-11-20T18:00');medium=create(c,agent_headers)
    now[0]=at('2026-11-21T12:00')
    sla=c.get(p,headers=owner).json()['sla']
    assert sla['resolution_breached'] and sla['is_late']
    now[0]=at('2026-11-22T12:00')
    assert not c.get(f'/tickets/{medium["id"]}',headers=owner).json()['sla']['is_late']

    version=c.get(p,headers=owner).json()['version']
    assert c.post(p+'/status',headers=owner,json={'status':'waiting_on_customer','version':version}).status_code==422
    r=c.post(p+'/status',headers=owner,json={'status':'waiting_on_customer','body':'Can you send details?','version':version})
    assert r.status_code==200 and r.json()['status']=='waiting_on_customer'
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM ticket_pauses WHERE ticket_id=%s AND resumed_at IS NULL',(urgent['id'],)).fetchone()[0]==1

    now[0]=at('2026-11-23T10:00');mp=f'/tickets/{medium["id"]}'
    r=c.post(mp+'/priority',headers=owner,json={'priority':'urgent'})
    assert r.status_code==200
    assert datetime.fromisoformat(r.json()['sla']['resolution_due_at'])==at('2026-11-20T18:30')
    assert r.json()['sla']['resolution_breached']
    e=event_types(c,medium['id'],owner)[-1]
    assert e['event_type']=='priority_changed'
    assert e['before_value']['resolution_due_at']!=e['after_value']['resolution_due_at']
    assert c.post(mp+'/priority',headers=owner,json={'priority':'small'}).json()['sla']['resolution_breached']

    assert c.post(p+'/customer-reply',headers=customer,json={'body':'Here are details'}).status_code==201
    assert c.get(p,headers=owner).json()['status']=='open'
    other=create(c,agent_headers);wait(c,other,agent_headers)
    now[0]=threshold(url,now[0])
    assert c.post('/admin/sweep',headers=SWEEP).json()['ticket_ids']==[other['id']]
    assert c.post('/admin/sweep',headers=SWEEP).json()['closed_count']==0
    closed=[e for e in event_types(c,other['id'],owner) if e['event_type']=='auto_closed']
    assert len(closed)==1 and closed[0]['actor']=='system'

    # Two tickets resolved at the same instant exercise both exact boundaries.
    boundary=[]
    for _ in range(2):
        t=create(c,agent_headers);tp=f'/tickets/{t["id"]}'
        assert c.post(tp+'/claim',headers=owner).status_code==200
        version=c.get(tp,headers=owner).json()['version']
        assert c.post(tp+'/status',headers=owner,json={'status':'resolved','version':version}).status_code==200
        boundary.append(t)
    resolved=now[0];now[0]=threshold(url,resolved)
    first=boundary[0];fp=f'/tickets/{first["id"]}'
    r=c.post(fp+'/customer-reply',headers={'X-Customer-Token':first['customer_token']},json={'body':'Reopen at exactly five days'})
    assert r.status_code==201 and r.json()['action']=='reopen'
    view=c.get(fp,headers=owner).json()
    assert view['sla']['cycle_number']==2 and view['assignee_id']==winner
    now[0]+=timedelta(minutes=1)
    second=boundary[1];sp=f'/tickets/{second["id"]}'
    original=c.get(sp,headers=owner).json()
    r=c.post(sp+'/customer-reply',headers={'X-Customer-Token':second['customer_token']},json={'body':'New linked request at 2701'})
    assert r.status_code==201 and r.json()['action']=='linked_new_ticket'
    linked=c.get(f'/tickets/{r.json()["ticket_id"]}',headers=owner).json()
    assert linked['previous_ticket_id']==second['id']
    assert [e['event_type'] for e in event_types(c,linked['id'],owner)]==['created','linked_ticket_created','public_reply']
    assert c.get(sp,headers=owner).json()==original

    for method in ['PUT','PATCH','DELETE']:
        assert c.request(method,p+'/events',headers=owner,json={}).status_code in (404,405)
    with psycopg.connect(url) as db:
        event_id=db.execute('SELECT id FROM events ORDER BY id LIMIT 1').fetchone()[0]
        for sql in ['UPDATE events SET actor=\'forged\' WHERE id=%s','DELETE FROM events WHERE id=%s']:
            with pytest.raises(psycopg.errors.RaiseException,match='append-only'):
                with db.transaction():db.execute(sql,(event_id,))

    timeline=event_types(c,urgent['id'],owner)
    assert [(e['event_type'],e['actor']) for e in timeline]==[
        ('created','customer'),('claimed',f'agent:{winner}'),('internal_note_added',f'agent:{winner}'),
        ('public_reply',f'agent:{winner}'),('public_reply',f'agent:{winner}'),('paused',f'agent:{winner}'),
        ('status_changed',f'agent:{winner}'),('public_reply','customer'),('resumed','customer'),('status_changed','customer')]
    assert [e['id'] for e in timeline]==sorted(e['id'] for e in timeline)
    stamps=[datetime.fromisoformat(e['created_at']) for e in timeline]
    assert stamps==sorted(stamps) and all(stamp.tzinfo for stamp in stamps)
    assert all('before_value' in e and 'after_value' in e for e in timeline)

    for route in ['/','/customer']:
        assert c.get(route).status_code==200
    html=rendered_ui(c,owner,urgent['id'])
    assert 'Team-only' in html['detail']
    assert '&lt;script&gt;' in html['detail']
    tags=Tags();tags.feed(html['detail']);assert 'script' not in tags.tags
    tickets=c.get('/tickets?assignee=all',headers=owner).json()
    flags=[t['sla']['is_late'] for t in tickets]
    assert flags==sorted(flags,reverse=True)
    import re
    rendered_ids=[int(i) for i in re.findall('data-ticket="(\\d+)"',html['list'])]
    flag_by_id={t['id']:t['sla']['is_late'] for t in tickets}
    assert [flag_by_id[i] for i in rendered_ids]==sorted(flags,reverse=True)
