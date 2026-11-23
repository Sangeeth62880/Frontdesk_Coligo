"""Final audit regressions: capability boundaries, abuse, rollback and wire safety."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from frontdesk.api import create_app
from frontdesk.http import RequestSafety
from tests.conftest import login_headers
from tests.test_concurrency import parallel
from tests.test_mutations import create


def test_capability_is_only_visible_to_assignee(harness, agent_headers):
    c, _, _ = harness
    t = create(c, agent_headers)
    p = f'/tickets/{t["id"]}'
    other = login_headers(c, 2)
    assert 'customer_token' not in c.get(p, headers=other).json()
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    assert 'customer_token' not in c.get(p, headers=agent_headers).json()
    assert c.get(p+'/customer-access',headers=agent_headers).json()['customer_token']==t['customer_token']
    assert c.get(p+'/customer-access',headers=other).status_code==403
    assert 'customer_token' not in c.get(p, headers=other).json()
    assert c.post(p+'/reassign',headers=other,json={'assignee_id':2}).status_code==403
    assert 'customer_token' not in c.get(p,headers=other).json()
    for headers in (agent_headers, other):
        assert all('customer_token' not in row for row in c.get('/tickets?assignee=all', headers=headers).json())
        assert c.post(p+'/priority', headers=headers, json={'priority':'small', 'customer_token':str(uuid4())}).status_code == 422
    assert c.post(p+'/reassign', headers=agent_headers, json={'assignee_id':2}).status_code == 200
    assert 'customer_token' not in c.get(p, headers=agent_headers).json()
    assert 'customer_token' not in c.get(p, headers=other).json()
    assert c.get(p+'/customer-access',headers=other).json()['customer_token']==t['customer_token']
    assert c.get(p+'/customer-access',headers=agent_headers).status_code==403


@pytest.mark.parametrize('field', ['subject', 'customer_email'])
def test_null_ticket_input_is_rejected(harness, agent_headers, field):
    c, _, _ = harness
    data = {'body':'Test description', 'subject':'Safe', 'customer_email':'safe@example.com', field:'bad\x00@example.com'}
    assert c.post('/tickets', headers=agent_headers, json=data).status_code == 422
    assert c.post('/customer/tickets', json=data).status_code == 422


def test_null_messages_login_and_huge_ids(harness, agent_headers):
    c, _, _ = harness
    t = create(c, agent_headers)
    for suffix in ('notes', 'messages', 'customer-reply'):
        h = {'X-Customer-Token':t['customer_token']} if suffix == 'customer-reply' else agent_headers
        assert c.post(f'/tickets/{t["id"]}/{suffix}', headers=h, json={'body':'bad\x00'}).status_code == 422
    assert c.post('/auth/login', json={'email':'bad\x00@example.com', 'password':'x'}).status_code == 422
    for ticket_id in ('-1', str(2**100)):
        for suffix in ('', '/events'):
            assert c.get(f'/tickets/{ticket_id}{suffix}', headers=agent_headers).status_code == 422
        for suffix, body in [('claim',{}), ('notes',{'body':'x'}), ('priority',{'priority':'small'}), ('status',{'status':'resolved','version':0}), ('agent-reopen',{}), ('reassign',{'assignee_id':1})]:
            assert c.post(f'/tickets/{ticket_id}/{suffix}', headers=agent_headers, json=body).status_code == 422
    assert c.post(f'/tickets/{t["id"]}/reassign', headers=agent_headers, json={'assignee_id':2**100}).status_code == 422


def test_streamed_body_limit_without_content_length():
    async def run():
        called = []
        async def app(scope, receive, send): called.append(True)
        messages = iter([{'type':'http.request', 'body':b'a'*32, 'more_body':True}, {'type':'http.request', 'body':b'b'*33, 'more_body':False}])
        async def receive(): return next(messages)
        out = []
        async def send(message): out.append(message)
        await RequestSafety(app, max_bytes=64)({'type':'http','method':'POST','headers':[]}, receive, send)
        assert not called
        assert out[0]['status'] == 413
        assert any(k == b'x-request-id' for k,v in out[0]['headers'])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, run()).result(timeout=10)


def test_body_limit_headers_and_no_request_secret_logs(harness, caplog):
    c, _, _ = harness
    caplog.set_level('INFO', logger='frontdesk.requests')
    r = c.post('/customer/tickets?token=QUERY_SECRET', content=b'x'*65537)
    assert r.status_code == 413
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert r.headers['x-request-id']
    assert 'QUERY_SECRET' not in '\n'.join(record.message for record in caplog.records if record.name == 'frontdesk.requests')
    assert c.get('/health').headers['x-request-id'] != r.headers['x-request-id']


def test_parallel_customer_intake_quota_and_recovery(harness, monkeypatch):
    _c, url, now = harness
    monkeypatch.setenv('FRONTDESK_INTAKE_LIMIT','3')
    # A separate clocked app permits an exact window recovery check.
    with TestClient(create_app(url, sweep_interval=0, clock=lambda:now[0])) as client:
        def post(c):
            return c.post('/customer/tickets', headers={'X-Forwarded-For':str(uuid4())}, json={'body':'Test description', 'subject':'Quota', 'customer_email':'q@example.com'})
        results = parallel(client, [post]*8)
        assert sorted(r.status_code for r in results) == [201]*3+[429]*5
        assert all(int(r.headers['retry-after']) > 0 for r in results if r.status_code == 429)
        with psycopg.connect(url) as db:
            assert db.execute('SELECT count(*) FROM tickets').fetchone()[0] == 3
        now[0] += timedelta(minutes=10, microseconds=1)
        assert post(client).status_code == 201


def test_database_outage_is_redacted_503(caplog):
    caplog.set_level('ERROR')
    with TestClient(create_app('postgresql://secret_user:secret_password@127.0.0.1:1/missing', sweep_interval=0)) as c:
        response = c.get('/health')
        assert response.status_code == 503
        assert response.json() == {'detail':'Database temporarily unavailable'}
        assert response.headers['x-request-id'] and response.headers['retry-after'] == '5'
        assert 'secret_password' not in caplog.text+response.text


def test_event_failure_rolls_back_entire_mutation(harness, agent_headers, monkeypatch):
    from frontdesk import service
    c, url, _ = harness
    t = create(c, agent_headers)
    p = f'/tickets/{t["id"]}'
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    before = c.get(p, headers=agent_headers).json()
    def fail(*args, **kwargs): raise psycopg.errors.CheckViolation('PRIVATE_SQL_SECRET')
    monkeypatch.setattr(service,'log_event',fail)
    r = c.post(p+'/messages', headers=agent_headers, json={'body':'Rollback me'})
    assert r.status_code == 503 and 'PRIVATE_SQL_SECRET' not in r.text
    assert c.get(p, headers=agent_headers).json() == before
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM public_messages').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 2


def test_customer_idor_including_linked_chain(harness, agent_headers):
    c, _, now = harness
    x, y = create(c, agent_headers), create(c, agent_headers)
    h = {'X-Customer-Token':x['customer_token']}
    p = f'/tickets/{y["id"]}'
    for suffix in ('customer-reply', 'reopen'):
        assert c.post(p+'/'+suffix, headers=h, json={'body':'Attack'} if suffix=='customer-reply' else {}).status_code == 404
    assert c.get(f'/customer/tickets/{y["id"]}', headers=h).status_code == 404
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    version = c.get(p, headers=agent_headers).json()['version']
    assert c.post(p+'/status', headers=agent_headers, json={'status':'resolved','version':version}).status_code == 200
    now[0] += timedelta(days=10)
    linked = c.post(p+'/reopen', headers={'X-Customer-Token':y['customer_token']}).json()['ticket']['id']
    assert c.get(f'/customer/tickets/{linked}', headers=h).status_code == 404
    assert {t['id'] for t in c.get('/customer/tickets', headers=h).json()} == {x['id']}


def test_static_traversal_cors_and_no_redirect(harness):
    c, _, _ = harness
    for path in ('/static/../.env','/static/%2e%2e/.env','/static/%2e%2e%2f.env','/static/%2e%2e%2ffrontdesk/api.py'):
        r = c.get(path)
        assert r.status_code == 404
    r = c.options('/auth/login', headers={'Origin':'https://evil.example','Access-Control-Request-Method':'POST'})
    assert 'access-control-allow-origin' not in r.headers
    assert c.get('/?next=https://evil.example', follow_redirects=False).status_code == 200


def test_startup_fails_before_migration_when_required_settings_missing(monkeypatch):
    from scripts import start
    called=[]
    monkeypatch.setattr(start,'migrate',lambda:called.append(True))
    monkeypatch.delenv('DATABASE_URL',raising=False)
    with pytest.raises(RuntimeError,match='DATABASE_URL'):start.main()
    assert not called
    monkeypatch.setenv('DATABASE_URL','postgresql://not-used')
    monkeypatch.setenv('RENDER','true')
    monkeypatch.delenv('FRONTDESK_DB_PASSWORD',raising=False)
    with pytest.raises(RuntimeError,match='FRONTDESK_DB_PASSWORD'):start.main()
    assert not called


def test_database_constraints_reject_invalid_rows(harness,agent_headers):
    c,url,now=harness
    t=create(c,agent_headers)
    with psycopg.connect(url) as db:
        cycle=db.execute('SELECT id FROM resolution_cycles WHERE ticket_id=%s',(t['id'],)).fetchone()[0]
        cases=[
            ("UPDATE tickets SET status='invalid' WHERE id=%s",(t['id'],),psycopg.errors.CheckViolation),
            ("UPDATE tickets SET priority='invalid' WHERE id=%s",(t['id'],),psycopg.errors.ForeignKeyViolation),
            ("UPDATE tickets SET subject=NULL WHERE id=%s",(t['id'],),psycopg.errors.NotNullViolation),
            ("UPDATE tickets SET assignee_id=999999 WHERE id=%s",(t['id'],),psycopg.errors.ForeignKeyViolation),
            ("INSERT INTO resolution_cycles(ticket_id,cycle_number,start_at) VALUES (%s,0,%s)",(t['id'],now[0]),psycopg.errors.CheckViolation),
            ("INSERT INTO ticket_pauses(ticket_id,cycle_id,paused_at,resumed_at) VALUES (%s,%s,%s,%s)",(t['id'],cycle,now[0],now[0]-timedelta(seconds=1)),psycopg.errors.CheckViolation),
            ("INSERT INTO public_messages(ticket_id,author_type,body) VALUES (%s,'agent','invalid actor')",(t['id'],),psycopg.errors.CheckViolation),
        ]
        for query,params,error in cases:
            with pytest.raises(error),db.transaction():db.execute(query,params)
        db.execute('INSERT INTO ticket_pauses(ticket_id,cycle_id,paused_at) VALUES (%s,%s,%s)',(t['id'],cycle,now[0]))
        with pytest.raises(psycopg.errors.UniqueViolation),db.transaction():
            db.execute('INSERT INTO ticket_pauses(ticket_id,cycle_id,paused_at) VALUES (%s,%s,%s)',(t['id'],cycle,now[0]))
        types=db.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name IN ('tickets','events','ticket_pauses','resolution_cycles') AND column_name LIKE '%%_at'").fetchall()
        assert types and all(row[0]=='timestamp with time zone' for row in types)


def test_hsts_on_render_only(harness,monkeypatch):
    c,_,_=harness
    monkeypatch.delenv('RENDER',raising=False)
    assert 'strict-transport-security' not in c.get('/').headers
    monkeypatch.setenv('RENDER','true')
    assert c.get('/').headers['strict-transport-security']=='max-age=31536000'
