import json

import psycopg
from fastapi.routing import APIRoute

from frontdesk.serializers import (
    MESSAGE_FIELDS,
    PRIVATE_TICKET_FIELDS,
    TICKET_FIELDS,
    customer_ticket,
)
from tests.test_mutations import create

MARKER='NOTE_MARKER_7f3a'


def test_model_columns_require_explicit_privacy_decision(api_db):
    with psycopg.connect(api_db) as db:
        columns={r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='tickets'")}
    assert not set(TICKET_FIELDS)&PRIVATE_TICKET_FIELDS
    assert columns==set(TICKET_FIELDS)|PRIVATE_TICKET_FIELDS
    # Future arbitrary fields never flow through the allowlist by default.
    row={name:None for name in columns};row['new_private_field']=MARKER
    message={name:None for name in MESSAGE_FIELDS}|{'agent_secret':MARKER}
    assert MARKER not in json.dumps(customer_ticket(row,[message]))


def test_notes_invisible_in_data_metadata_headers_errors_and_logs(harness,agent_headers,caplog):
    c,url,_now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    customer={'X-Customer-Token':t['customer_token']}
    reads=['/customer/tickets',f'/customer/tickets/{t["id"]}','/export.csv']
    before={path:c.get(path,headers=customer).content for path in reads}
    before_sla=c.get(p,headers=agent_headers).json()['sla']
    caplog.set_level('DEBUG')
    assert c.post(p+'/notes',headers=agent_headers,json={'body':MARKER}).status_code==201
    assert {path:c.get(path,headers=customer).content for path in reads}==before
    assert c.get(p,headers=agent_headers).json()['sla']==before_sla
    with psycopg.connect(url) as db:
        assert db.execute('SELECT first_replied_at FROM tickets').fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM ticket_pauses').fetchone()[0]==0
    # Exercise every registered route with no agent credentials. Inventory equality
    # forces an explicit test decision when the API grows.
    expected={
        ('POST','/auth/login'),('GET','/auth/me'),('POST','/auth/logout'),('GET','/health'),('GET','/agents'),('GET','/tickets'),('GET','/tickets/export.csv'),('POST','/tickets'),
        ('POST','/customer/tickets'),('GET','/customer/tickets'),('GET','/customer/tickets/{ticket_id}'),
        ('GET','/export.csv'),('POST','/tickets/{ticket_id}/notes'),('POST','/tickets/{ticket_id}/claim'),
        ('GET','/tickets/{ticket_id}'),('GET','/tickets/{ticket_id}/events'),('GET','/tickets/{ticket_id}/customer-access'),
        ('POST','/tickets/{ticket_id}/messages'),('POST','/tickets/{ticket_id}/customer-reply'),
        ('POST','/tickets/{ticket_id}/status'),('POST','/tickets/{ticket_id}/priority'),
        ('POST','/tickets/{ticket_id}/agent-reopen'),('POST','/tickets/{ticket_id}/reassign'),('POST','/tickets/{ticket_id}/reopen'),('POST','/admin/sweep')}
    registered={(m,r.path) for r in c.app.routes if isinstance(r,APIRoute) and r.include_in_schema for m in r.methods}
    assert registered==expected-{('GET','/health')}
    for headers in [{},customer]:
        for method,path in expected:
            response=c.request(method,path.replace('{ticket_id}',str(t['id'])),headers=headers,**({'json':{'body':'Public follow-up'}} if method=='POST' else {}))
            assert response.status_code<500
            assert MARKER not in response.text+str(response.headers)
            assert 'internal_notes' not in response.text
        for path in ['/','/customer','/docs','/redoc','/openapi.json','/search?q=Public','/customer/messages']:
            response=c.get(path,headers=headers)
            assert MARKER not in response.text+str(response.headers)
    for endpoint in ['/notes','/messages','/status']:
        response=c.post(p+endpoint,headers=agent_headers,json={'body':MARKER*1001})
        assert response.status_code==422
        assert MARKER not in response.text+str(response.headers)
    with psycopg.connect(url) as db:
        assert MARKER not in str(db.execute('SELECT actor,event_type,before_value,after_value FROM events').fetchall())
    assert MARKER not in caplog.text


def test_agent_endpoints_private_no_store(harness,agent_headers):
    c,_,_=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    for path in ['/','/agents','/tickets?assignee=all',p,p+'/events']:
        response=c.get(path,headers=agent_headers)
        assert response.status_code==200
        assert set(response.headers['cache-control'].split(', '))=={'private','no-store'}
    response=c.post(p+'/notes',headers=agent_headers,json={'body':'private'})
    assert response.headers['cache-control']=='private, no-store'
