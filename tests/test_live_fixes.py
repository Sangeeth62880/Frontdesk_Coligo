import psycopg
import pytest

from tests.conftest import login_headers


def test_owner_status_priority_and_unassigned_triage(harness, agent_headers):
    c, _, _ = harness
    other = login_headers(c, 2)
    t = c.post('/tickets', headers=agent_headers, json={'body':'Test description', 'subject':'Permission regression','customer_email':'permissions@example.com'}).json()
    p = f'/tickets/{t["id"]}'
    def snapshot():
        detail = c.get(p, headers=agent_headers).json()
        return detail, c.get(p+'/events', headers=agent_headers).json()
    before = snapshot()
    response = c.post(p+'/status', headers=agent_headers, json={'status':'resolved','version':before[0]['version']})
    assert response.status_code == 409 and 'Claim this ticket first' in response.json()['detail']
    assert snapshot() == before
    assert c.post(p+'/priority', headers=other, json={'priority':'urgent'}).status_code == 200
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    before = snapshot()
    for endpoint, body in [('/status', {'status':'resolved','version':before[0]['version']}),('/priority', {'priority':'small'})]:
        response = c.post(p+endpoint, headers=other, json=body)
        assert response.status_code == 409 and isinstance(response.json()['detail'], str)
        assert snapshot() == before
    assert c.post(p+'/priority', headers=agent_headers, json={'priority':'small'}).status_code == 200
    assert c.post(p+'/status', headers=agent_headers, json={'status':'resolved','version':snapshot()[0]['version']}).status_code == 200


def test_resolution_public_message_is_atomic_idempotent_and_first_reply(harness, agent_headers):
    c, _, _ = harness
    t = c.post('/tickets', headers=agent_headers, json={'body':'Test description', 'subject':'Resolution message','customer_email':'resolved@example.com'}).json()
    p = f'/tickets/{t["id"]}'
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    assert c.post(p+'/notes', headers=agent_headers, json={'body':'Private investigation'}).status_code == 201
    assert c.get(p, headers=agent_headers).json()['first_reply_at'] is None
    version = c.get(p, headers=agent_headers).json()['version']
    payload = {'status':'resolved','body':'The issue is fixed.','version':version}
    before = c.get(p+'/events', headers=agent_headers).json()
    headers = agent_headers | {'Idempotency-Key':'resolution-once'}
    first = c.post(p+'/status', headers=headers, json=payload)
    assert first.status_code == 200
    assert c.post(p+'/status', headers=headers, json=payload).json() == first.json()
    detail = c.get(p, headers=agent_headers).json()
    assert detail['status'] == 'resolved' and detail['first_reply_at'] is not None
    assert [m['body'] for m in detail['messages']] == ['Test description','The issue is fixed.']
    public = c.get('/customer'+p, headers={'X-Customer-Token':t['customer_token']}).json()
    assert [m['body'] for m in public['messages']] == ['Test description','The issue is fixed.']
    assert 'Private investigation' not in str(public)
    after = c.get(p+'/events', headers=agent_headers).json()
    assert [e['event_type'] for e in after[len(before):]] == ['public_reply','status_changed']
    assert c.post(p+'/status', headers=headers, json=payload | {'body':'Different'}).status_code == 409
    assert c.get(p+'/events', headers=agent_headers).json() == after


def test_resolution_without_message_still_works(harness, agent_headers):
    c, _, _ = harness
    t = c.post('/tickets', headers=agent_headers, json={'body':'Test description', 'subject':'No message','customer_email':'resolved@example.com'}).json()
    p = f'/tickets/{t["id"]}'
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    version = c.get(p, headers=agent_headers).json()['version']
    assert c.post(p+'/status', headers=agent_headers, json={'status':'resolved','version':version}).status_code == 200
    assert c.get(p, headers=agent_headers).json()['messages'][0]['body'] == 'Test description'
    assert len(c.get(p, headers=agent_headers).json()['messages']) == 1


@pytest.mark.parametrize('route', ['/tickets','/customer/tickets'])
def test_description_is_first_customer_message_and_does_not_change_clocks(harness, agent_headers, route):
    c, url, _ = harness
    description = '<img src=x onerror="window.XSS_EXECUTED=true"> Customer details'
    payload = {'subject':'Description test','body':description,'customer_email':'description@example.com'}
    t = c.post(route, headers=agent_headers, json=payload).json()
    view = c.get(f'/tickets/{t["id"]}', headers=agent_headers).json()
    assert len(view['messages']) == 1
    assert view['messages'][0]['body'] == description and view['messages'][0]['author_type'] == 'customer'
    assert view['first_replied_at'] is None and view['first_reply_at'] is None
    access = {'X-Customer-Token':t['customer_token']}
    assert c.get(f'/customer/tickets/{t["id"]}', headers=access).json()['messages'][0]['body'] == description
    exported = c.get('/export.csv', headers=access)
    assert description.replace('"','""') in exported.text
    control = c.post(route, headers=agent_headers, json=payload | {'body':'Ordinary description'}).json()
    other = c.get(f'/tickets/{control["id"]}', headers=agent_headers).json()
    assert view['sla'] == other['sla'] and view['start_at'] == other['start_at']
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM ticket_pauses').fetchone()[0] == 0
        event = c.get(f'/tickets/{t["id"]}/events', headers=agent_headers).json()[0]
        assert event['after_value']['message_id'] == view['messages'][0]['id']


@pytest.mark.parametrize('route', ['/tickets','/customer/tickets'])
@pytest.mark.parametrize('body', [None,'','   ','bad\x00body','x'*10001])
def test_description_validation(harness, agent_headers, route, body):
    c, _, _ = harness
    payload = {'subject':'Invalid description','customer_email':'description@example.com','body':body}
    assert c.post(route, headers=agent_headers, json=payload).status_code == 422
    payload.pop('body')
    assert c.post(route, headers=agent_headers, json=payload).status_code == 422


def test_every_event_type_has_an_explicit_ui_label(harness, agent_headers):
    from frontdesk.events import PAYLOAD_FIELDS
    from tests.test_mutations import create
    from tests.test_security_hardening import rendered_ui
    c, _, _ = harness
    ticket = create(c,agent_headers)
    ui = rendered_ui(c,agent_headers,ticket['id'])
    assert set(ui['eventLabels']) == set(PAYLOAD_FIELDS)
    assert all(value and value != key for key,value in ui['eventLabels'].items())
    assert 'Source: customer' in ui['detail']


def test_customer_token_failures_are_uniform_and_valid_body_errors_stay_422(harness, agent_headers):
    from uuid import uuid4

    from tests.test_mutations import create
    c, _, _ = harness
    ticket = create(c,agent_headers)
    cases = [None,'wrong-format','0'*32,str(uuid4()),str(uuid4()).upper(),'x'*1000]
    expected = {'detail':'Customer access token invalid'}
    routes = [('GET','/customer/tickets'),('GET',f'/customer/tickets/{ticket["id"]}'),('GET','/export.csv'),('POST',f'/tickets/{ticket["id"]}/reopen'),('POST',f'/tickets/{ticket["id"]}/customer-reply')]
    for token in cases:
        headers = {} if token is None else {'X-Customer-Token':token}
        for method,path in routes:
            response = c.request(method,path,headers=headers,json={'body':'Valid request'})
            assert response.status_code == 401 and response.json() == expected
    for body in ('','bad\x00body','x'*10001):
        response = c.post(f'/tickets/{ticket["id"]}/customer-reply',headers={'X-Customer-Token':ticket['customer_token']},json={'body':body})
        assert response.status_code == 422


def test_late_export_retains_breach_target_across_priority_completion_and_reopen(harness, agent_headers):
    import csv
    import io
    from datetime import datetime, timedelta

    from frontdesk.business_time import Calendar
    c, url, now = harness
    ticket = c.post('/tickets',headers=agent_headers,json={'subject':'=SUM(1,2)','body':'Public description','customer_email':'late@example.com','priority':'urgent'}).json()
    p = f'/tickets/{ticket["id"]}'
    assert c.post(p+'/claim',headers=agent_headers).status_code == 200
    assert c.post(p+'/notes',headers=agent_headers,json={'body':'NEVER_EXPORT_PRIVATE_NOTE'}).status_code == 201
    due = datetime.fromisoformat(c.get(p,headers=agent_headers).json()['sla']['resolution_due_at'])
    with psycopg.connect(url) as db:
        calendar = Calendar(frozenset(row[0] for row in db.execute('SELECT day FROM holidays')))
    now[0] = calendar.add(due,660)
    assert c.get('/tickets/export.csv?late=true').status_code == 401
    response = c.get('/tickets/export.csv?late=true',headers=agent_headers)
    assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
    assert all(secret not in response.text for secret in ('NEVER_EXPORT_PRIVATE_NOTE','customer_token',ticket['customer_token'],'Public description','late@example.com'))
    rows = list(csv.DictReader(io.StringIO(response.text)))
    resolution = next(row for row in rows if row['breached_target']=='resolution')
    assert float(resolution['overshoot_working_minutes']) == 660
    assert datetime.fromisoformat(resolution['due_time']) == due
    assert resolution['assignee']=='Meera' and resolution['subject']=="'=SUM(1,2)"
    assert {row['breached_target'] for row in rows} == {'first_reply','resolution'}
    assert c.post(p+'/priority',headers=agent_headers,json={'priority':'small'}).status_code == 200
    view = c.get(p,headers=agent_headers).json()
    assert datetime.fromisoformat(view['sla']['resolution_due_at']) > now[0]
    target = next(target for target in view['late_targets'] if target['target']=='resolution')
    assert target['working_minutes'] == 660 and datetime.fromisoformat(target['due_at']) == due
    assert c.post(p+'/status',headers=agent_headers,json={'status':'resolved','version':view['version']}).status_code == 200
    now[0] += timedelta(days=1)
    assert c.post(p+'/agent-reopen',headers=agent_headers).status_code == 200
    targets = c.get(p,headers=agent_headers).json()['late_targets']
    assert [(target['cycle_number'],target['working_minutes']) for target in targets if target['target']=='resolution'] == [(1,660)]


def test_late_working_time_excludes_paused_time(harness, agent_headers):
    from datetime import datetime

    from frontdesk.business_time import Calendar
    c, url, now = harness
    ticket = c.post('/tickets',headers=agent_headers,json={'subject':'Late waiting','body':'Initial question','customer_email':'wait@example.com','priority':'urgent'}).json()
    p = f'/tickets/{ticket["id"]}'
    assert c.post(p+'/claim',headers=agent_headers).status_code == 200
    view = c.get(p,headers=agent_headers).json()
    due = datetime.fromisoformat(view['sla']['resolution_due_at'])
    with psycopg.connect(url) as db:
        calendar = Calendar(frozenset(row[0] for row in db.execute('SELECT day FROM holidays')))
    now[0] = calendar.add(due,60)
    assert c.post(p+'/status',headers=agent_headers,json={'status':'waiting_on_customer','body':'Please confirm the workspace','version':view['version']}).status_code == 200
    now[0] = calendar.add(now[0],1080)
    targets = c.get(p,headers=agent_headers).json()['late_targets']
    assert next(target for target in targets if target['target']=='resolution')['working_minutes'] == 60


def test_clean_seed_has_one_late_ticket_and_no_test_subjects(harness, agent_headers):
    from datetime import timedelta

    from psycopg.rows import dict_row

    from scripts.seed_demo import seed_cases
    c, url, now = harness
    now[0] -= timedelta(days=7)
    with psycopg.connect(url,row_factory=dict_row) as db:
        assert len(seed_cases(db,now[0])) == 8
    tickets = c.get('/tickets?assignee=all',headers=agent_headers).json()
    assert sum(ticket['sla']['is_late'] for ticket in tickets) == 1
    assert all('verification' not in ticket['subject'].lower() and '<' not in ticket['subject'] for ticket in tickets)
