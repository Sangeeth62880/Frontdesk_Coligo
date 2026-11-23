"""Generate request bodies from the application's published OpenAPI schemas."""
import json
from pathlib import Path
from uuid import uuid4

import psycopg
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis_jsonschema import from_schema
from psycopg import sql
from psycopg.conninfo import make_conninfo

from scripts.migrate import main as migrate
from tests.test_mutations import create


@settings(max_examples=150, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture,HealthCheck.too_slow])
@given(data=st.data())
def test_openapi_generated_requests_never_500(harness,agent_headers,data):
    c,_,_=harness
    schemas=c.get('/openapi.json').json()['components']['schemas']
    name=data.draw(st.sampled_from(['AgentTicketInput','NoteInput','MessageInput','StatusInput','PriorityInput','ReassignInput']))
    body=data.draw(from_schema(schemas[name]))
    created=c.post('/tickets',headers=agent_headers,json={'body':'Test description', 'subject':'Schema fuzz fixture','customer_email':'schema@example.com'})
    assert created.status_code==201
    ticket=created.json()
    route={'AgentTicketInput':'/tickets','NoteInput':f'/tickets/{ticket["id"]}/notes','MessageInput':f'/tickets/{ticket["id"]}/messages','StatusInput':f'/tickets/{ticket["id"]}/status','PriorityInput':f'/tickets/{ticket["id"]}/priority','ReassignInput':f'/tickets/{ticket["id"]}/reassign'}[name]
    response=c.post(route,headers=agent_headers,json=body)
    assert response.status_code in (200,201,403,409,422), (name,response.status_code,response.text)
    if response.status_code>=400:assert set(response.json())=={'detail'}
    assert response.headers['cache-control']=='private, no-store'
    extra=c.post(route,headers=agent_headers,json=body|{'unexpected_audit_field':True})
    assert extra.status_code==422


def test_wire_fuzz_and_auth_inventory(harness,agent_headers):
    c,_,_=harness
    ticket=create(c,agent_headers)
    for body in ('{','[]','null','"string"','{"subject":"x","subject":"y"}'):
        response=c.post('/tickets',headers=agent_headers,content=body)
        assert response.status_code==422
        assert set(response.json())=={'detail'}
    for media in ('text/plain','application/xml','application/octet-stream'):
        r=c.post('/tickets',headers=agent_headers|{'Content-Type':media},content='{"subject":"x","customer_email":"a@example.com"}')
        assert r.status_code==422
    for subject in ('👩🏽‍💻','\u202eRTL','e\u0301','=SUM(A1:A2)','x'*300):
        r=c.post('/tickets',headers=agent_headers,json={'body':'Test description', 'subject':subject,'customer_email':'a@example.com'})
        assert r.status_code==201
    assert c.post('/tickets',headers=agent_headers,json={'body':'Test description', 'subject':'x'*301,'customer_email':'a@example.com'}).status_code==422
    r=c.get(f'/tickets/{ticket["id"]}',headers=[('Authorization','Bearer malformed'),('Authorization',agent_headers['Authorization'])])
    assert r.status_code==401
    r=c.get('/tickets/',headers=agent_headers,follow_redirects=False)
    assert r.status_code==307 and r.headers['location'].endswith('/tickets')
    schema=c.get('/openapi.json').json()
    inventory=[]
    customer={('/customer/tickets','get'),('/customer/tickets/{ticket_id}','get'),('/tickets/{ticket_id}/customer-reply','post'),('/tickets/{ticket_id}/reopen','post'),('/export.csv','get')}
    for path,methods in schema['paths'].items():
        for method in methods:
            if method not in ('get','post'):continue
            mode='public' if (path,method) in (('/customer/tickets','post'),('/auth/login','post')) else 'customer' if (path,method) in customer else 'sweep' if path=='/admin/sweep' else 'agent'
            inventory.append({'method':method.upper(),'path':path,'auth':mode})
            if mode in ('agent','customer','sweep'):
                r=c.request(method,path.replace('{ticket_id}',str(ticket['id'])),json={} if method=='post' else None)
                assert r.status_code==401,(path,r.text)
    Path('output/audit/routes.json').write_text(json.dumps(inventory,indent=2))


def test_fresh_migration_and_rerun_preserve_trigger_and_data(api_db,monkeypatch):
    schema='audit_migrate_'+uuid4().hex
    with psycopg.connect(api_db,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        isolated=make_conninfo(api_db,options=f'-csearch_path={schema}')
        monkeypatch.setenv('DATABASE_URL',isolated)
        try:
            migrate()
            with psycopg.connect(isolated) as db:
                before=db.execute('SELECT name FROM schema_migrations ORDER BY name').fetchall()
                agents=db.execute('SELECT id,name,email FROM agents ORDER BY id').fetchall()
            migrate()
            with psycopg.connect(isolated) as db:
                assert db.execute('SELECT name FROM schema_migrations ORDER BY name').fetchall()==before
                assert db.execute('SELECT id,name,email FROM agents ORDER BY id').fetchall()==agents
                assert len(before)==len(list(Path('migrations').glob('*.sql')))
                names={r[0] for r in db.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='events'::regclass AND NOT tgisinternal")}
                assert names=={'events_immutable','events_no_truncate','events_server_timestamp'}
        finally:admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
