from datetime import timedelta

import psycopg

from tests.test_mutations import create, event_types


def test_agent_creation_has_stored_null_reply_target(harness, agent_headers):
    c, url, _now = harness
    ticket = c.post('/tickets', headers=agent_headers, json={'subject':'On behalf', 'customer_email':'a@example.com', 'source':'agent'}).json()
    view = c.get(f'/tickets/{ticket["id"]}', headers=agent_headers).json()
    assert view['sla']['first_reply_due_at'] is None
    with psycopg.connect(url) as db:
        assert db.execute('SELECT first_reply_required, first_reply_due_at FROM tickets').fetchone() == (False, None)


def test_completed_on_time_never_becomes_late_and_late_reply_sticks(harness, agent_headers):
    c, _, now = harness
    ticket = create(c, agent_headers)
    path = f'/tickets/{ticket["id"]}'
    assert c.post(path+'/claim', headers=agent_headers).status_code == 200
    assert c.post(path+'/status', headers=agent_headers, json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'resolved'}).status_code == 200
    now[0] += timedelta(days=10)
    assert c.get(path, headers=agent_headers).json()['sla']['is_late'] is False
    other = create(c, agent_headers)
    path = f'/tickets/{other["id"]}'
    now[0] += timedelta(days=1)
    assert c.post(path+'/claim', headers=agent_headers).status_code == 200
    assert c.post(path+'/messages', headers=agent_headers, json={'body':'Late response'}).status_code == 201
    sla = c.get(path, headers=agent_headers).json()['sla']
    assert sla['first_reply_breached'] and not sla['resolution_breached']
    assert sla['is_late'] and sla['breached_targets'] == ['first_reply']


def test_claim_reassign_wait_and_invalid_transitions(harness, agent_headers):
    c, _, _now = harness
    t = create(c, agent_headers)
    path = f'/tickets/{t["id"]}'
    assert c.post(path+'/claim', headers=agent_headers).status_code == 200
    assert c.post(path+'/claim', headers=agent_headers).status_code == 200
    assert len([e for e in event_types(c,t['id'],agent_headers) if e['event_type']=='claimed']) == 1
    before = c.get(path,headers=agent_headers).json()['sla']
    assert c.post(path+'/reassign',headers=agent_headers,json={'assignee_id':2}).status_code == 200
    assert c.get(path,headers=agent_headers).json()['sla'] == before
    e = event_types(c,t['id'],agent_headers)[-1]
    assert e['before_value']=={'assignee_id':1} and e['after_value']=={'assignee_id':2}
    assert c.post(path+'/status',headers=agent_headers,json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'waiting_on_customer'}).status_code == 422
    assert c.post(path+'/status',headers=agent_headers,json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'closed'}).status_code == 409
    assert c.post(path+'/status',headers=agent_headers,json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'open'}).status_code == 409


def test_customer_completed_reply_links_or_reopens_and_agent_reopen(harness, agent_headers):
    c, url, now = harness
    t = create(c,agent_headers)
    path=f'/tickets/{t["id"]}'
    c.post(path+'/claim',headers=agent_headers)
    c.post(path+'/status',headers=agent_headers,json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'resolved'})
    r=c.post(path+'/customer-reply',headers={'X-Customer-Token':t['customer_token']},json={'body':'Again'})
    assert r.status_code==201 and r.json()['action']=='reopen'
    assert c.get(path,headers=agent_headers).json()['assignee_id']==1
    c.post(path+'/status',headers=agent_headers,json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'resolved'})
    r=c.post(path+'/status',headers=agent_headers,json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'open'})
    assert r.status_code==200 and r.json()['action']=='reopen'
    assert event_types(c,t['id'],agent_headers)[-1]['actor']=='agent:1'
    c.post(path+'/status',headers=agent_headers,json={"version": c.get((path+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'resolved'})
    before=event_types(c,t['id'],agent_headers)
    now[0]+=timedelta(days=12)
    r=c.post(path+'/customer-reply',headers={'X-Customer-Token':t['customer_token']},json={'body':'New request'})
    assert r.status_code==201 and r.json()['action']=='linked_new_ticket'
    assert event_types(c,t['id'],agent_headers)==before
    with psycopg.connect(url) as db:
        assert db.execute('SELECT previous_ticket_id FROM tickets WHERE id=%s',(r.json()['ticket_id'],)).fetchone()[0]==t['id']
        assert db.execute('SELECT body FROM public_messages WHERE ticket_id=%s',(r.json()['ticket_id'],)).fetchone()[0]=='New request'


def test_reopen_does_not_turn_on_time_first_cycle_into_a_reply_breach(harness,agent_headers):
    c,_,now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    version=c.get(p,headers=agent_headers).json()['version']
    c.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':version})
    now[0]+=timedelta(days=2)
    r=c.post(p+'/reopen',headers={'X-Customer-Token':t['customer_token']})
    assert r.status_code==200
    assert not r.json()['sla']['first_reply_breached']
    assert not r.json()['sla']['is_late']


def test_completed_cycle_outcome_is_independent_of_ticket_history(harness,agent_headers):
    c,url,now=harness;t=create(c,agent_headers,'urgent');p=f'/tickets/{t["id"]}'
    c.post(p+'/claim',headers=agent_headers)
    c.post(p+'/messages',headers=agent_headers,json={'body':'Timely'})
    now[0]+=timedelta(days=1)
    version=c.get(p,headers=agent_headers).json()['version']
    c.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':version})
    c.post(p+'/reopen',headers={'X-Customer-Token':t['customer_token']})
    version=c.get(p,headers=agent_headers).json()['version']
    r=c.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':version})
    assert r.json()['sla']['resolution_breached']
    assert not r.json()['sla']['cycle_resolution_breached']
    with psycopg.connect(url) as db:
        assert db.execute('SELECT breached FROM resolution_cycles ORDER BY cycle_number').fetchall()==[(True,),(False,)]


def test_agent_can_create_link_from_closed_without_editing_it(harness,agent_headers):
    from tests.test_sweep import SWEEP, threshold, wait
    c,url,now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    wait(c,t,agent_headers);now[0]=threshold(url,now[0])
    assert c.post('/admin/sweep',headers=SWEEP).json()['closed_count']==1
    old=c.get(p,headers=agent_headers).json()
    r=c.post(p+'/agent-reopen',headers=agent_headers)
    assert r.status_code==201 and r.json()['action']=='linked_new_ticket'
    assert r.json()['ticket']['previous_ticket_id']==t['id']
    assert c.get(p,headers=agent_headers).json()==old
    assert event_types(c,r.json()['ticket']['id'],agent_headers)[-1]['actor']=='agent:1'


import pytest


@pytest.mark.parametrize('old',['open','waiting_on_customer','resolved','closed'])
@pytest.mark.parametrize('new',['open','waiting_on_customer','resolved','closed'])
def test_status_transition_matrix(harness,agent_headers,old,new):
    from tests.test_sweep import SWEEP, threshold, wait
    c,url,now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    c.post(p+'/claim',headers=agent_headers)
    if old in ('waiting_on_customer','closed'):
        wait(c,t,agent_headers)
        if old=='closed':
            now[0]=threshold(url,now[0]);c.post('/admin/sweep',headers=SWEEP)
    elif old=='resolved':
        version=c.get(p,headers=agent_headers).json()['version']
        c.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':version})
    version=c.get(p,headers=agent_headers).json()['version']
    allowed={('open','waiting_on_customer'),('waiting_on_customer','open'),('open','resolved'),('waiting_on_customer','resolved'),('resolved','open')}
    response=c.post(p+'/status',headers=agent_headers,json={'status':new,'version':version,'body':'Public question'})
    assert response.status_code==(200 if (old,new) in allowed else 409),response.text


@pytest.mark.parametrize('state',['resolved','closed'])
def test_claim_completed_conflicts(harness,agent_headers,state):
    from tests.test_sweep import SWEEP, threshold, wait
    c,url,now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    c.post(p+'/claim',headers=agent_headers)
    if state=='closed':
        wait(c,t,agent_headers);now[0]=threshold(url,now[0]);c.post('/admin/sweep',headers=SWEEP)
    else:
        version=c.get(p,headers=agent_headers).json()['version']
        c.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':version})
    assert c.post(p+'/claim',headers=agent_headers).status_code==409
    assert c.post(p+'/claim',headers=agent_headers|{'X-Agent-Id':'2'}).status_code==409


def test_agent_sla_snapshot_matches_stored_flags(harness,agent_headers):
    c,url,now=harness;t=create(c,agent_headers,'urgent');p=f'/tickets/{t["id"]}'
    now[0]+=timedelta(days=1)
    for view in [c.get(p,headers=agent_headers).json(),c.get('/tickets?assignee=all',headers=agent_headers).json()[0]]:
        for key in ['first_reply_due_at','first_reply_breached','resolution_breached']:
            assert view[key]==view['sla'][key]
        assert view['resolution_breached']
    with psycopg.connect(url) as db:
        assert db.execute('SELECT first_reply_breached,resolution_breached FROM tickets').fetchone()==(True,True)
