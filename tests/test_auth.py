"""Credential identity, lifetime, isolation and secret-handling contracts."""
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from frontdesk.api import create_app
from frontdesk.auth import hash_password, token_hash, verify_password
from scripts.seed_demo import seed
from scripts.set_agent_password import set_password
from tests.conftest import TEST_PASSWORD, login_headers


@pytest.fixture
def auth_harness(api_db):
    instant = [datetime(2026, 11, 23, 4, 30, tzinfo=UTC)]
    app = create_app(api_db, sweep_token='test-sweep-secret', sweep_interval=0, auth_clock=lambda: instant[0])
    with TestClient(app) as client:
        yield client, api_db, instant


def signin(c, email='meera@arvo.example', password=TEST_PASSWORD):
    return c.post('/auth/login', json={'email': email, 'password': password})


def test_login_me_logout_absolute_lifetime(auth_harness):
    c, url, instant = auth_harness
    response = signin(c, '  MEERA@ARVO.EXAMPLE  ')
    assert response.status_code == 200
    data = response.json()
    assert data['agent'] == {'id': 1, 'name': 'Meera'}
    assert len(bytes.fromhex(data['token'])) == 32
    assert datetime.fromisoformat(data['expires_at']) == instant[0] + timedelta(hours=12)
    headers = {'Authorization': 'Bearer '+data['token']}
    assert c.get('/auth/me', headers=headers).json() == data['agent']
    instant[0] += timedelta(hours=11, minutes=59)
    assert c.get('/auth/me', headers=headers).status_code == 200
    with psycopg.connect(url) as db:
        assert db.execute('SELECT expires_at FROM agent_sessions').fetchone()[0] == datetime.fromisoformat(data['expires_at'])
    instant[0] += timedelta(minutes=1)
    assert c.get('/auth/me', headers=headers).status_code == 401
    fresh = login_headers(c, 1)
    assert c.post('/auth/logout', headers=fresh).status_code == 200
    assert c.get('/auth/me', headers=fresh).status_code == 401


def test_identical_failures_and_equal_password_work(auth_harness, monkeypatch, caplog):
    c, url, _ = auth_harness
    with psycopg.connect(url) as db:
        db.execute('UPDATE agents SET is_active=false WHERE id=2')
        db.execute('UPDATE agents SET password_hash=NULL WHERE id=3')
    from frontdesk import auth
    original = auth.hashlib.scrypt
    calls = []
    def traced(*args, **kwargs):
        calls.append({k: v for k, v in kwargs.items() if k != 'salt'})
        return original(*args, **kwargs)
    monkeypatch.setattr(auth.hashlib, 'scrypt', traced)
    responses = [signin(c, email, password) for email, password in [
        ('meera@arvo.example', 'wrong-password'), ('unknown@arvo.example', TEST_PASSWORD),
        ('arun@arvo.example', TEST_PASSWORD), ('divya@arvo.example', TEST_PASSWORD)]]
    assert [r.status_code for r in responses] == [401]*4
    assert all(r.json() == {'detail': 'Invalid email or password'} for r in responses)
    assert len(calls) == 4 and all(work == calls[0] for work in calls)
    assert len([r for r in caplog.records if r.name == 'frontdesk.auth']) == 4
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 0


def test_database_throttle_normalization_recovery_across_instances(auth_harness):
    c, url, instant = auth_harness
    for _ in range(5):
        assert signin(c, 'MEERA@arvo.example', 'wrong').status_code == 401
    with TestClient(create_app(url, auth_clock=lambda: instant[0], sweep_interval=0)) as second:
        blocked = signin(second)
        assert blocked.status_code == 429 and blocked.headers['retry-after'] == '600'
        instant[0] += timedelta(minutes=10) - timedelta(microseconds=1)
        assert signin(second).status_code == 429
        instant[0] += timedelta(microseconds=1)
        assert signin(second).status_code == 200
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM agent_login_attempts').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 0


def test_failure_window_resets(auth_harness):
    c, _, instant = auth_harness
    for _ in range(4):
        assert signin(c, password='wrong').status_code == 401
    instant[0] += timedelta(minutes=10)
    assert signin(c, password='wrong').status_code == 401
    assert signin(c).status_code == 200


# Every other API route must require an agent session. New routes automatically
# enter this test unless deliberately listed as public/capability/sweep routes.
NON_AGENT_ROUTES = {
    '/', '/customer', '/health', '/auth/login', '/admin/sweep', '/export.csv',
    '/customer/tickets', '/customer/tickets/{ticket_id}',
    '/tickets/{ticket_id}/customer-reply', '/tickets/{ticket_id}/reopen',
}


@pytest.mark.parametrize('credential', ['missing', 'malformed', 'expired', 'revoked', 'inactive', 'customer', 'sweep'])
def test_all_agent_routes_reject_invalid_sessions(auth_harness, credential):
    c, url, instant = auth_harness
    headers = login_headers(c, 1)
    token = headers['Authorization'][7:]
    if credential == 'missing': headers = {}
    elif credential == 'malformed': headers = {'Authorization': 'Bearer invalid token', 'X-Agent-Id': 'not-an-integer'}
    elif credential == 'customer': headers = {'Authorization': 'Bearer '+str(uuid4()), 'X-Customer-Token': str(uuid4())}
    elif credential == 'sweep': headers = {'Authorization': 'Bearer test-sweep-secret'}
    elif credential == 'revoked': assert c.post('/auth/logout', headers=headers).status_code == 200
    elif credential == 'expired': instant[0] += timedelta(hours=12)
    elif credential == 'inactive':
        with psycopg.connect(url) as db: db.execute('UPDATE agents SET is_active=false WHERE id=1')
    tested = set()
    for route in c.app.routes:
        if not isinstance(route, APIRoute) or route.path in NON_AGENT_ROUTES: continue
        for method in route.methods:
            response = c.request(method, route.path.replace('{ticket_id}', '1'), headers=headers, json={} if method == 'POST' else None)
            assert response.status_code == 401, (method, route.path, response.text)
            assert token not in response.text
            tested.add((method, route.path))
    assert ('GET', '/agents') in tested and ('POST', '/tickets/{ticket_id}/reassign') in tested


def test_header_cannot_impersonate_and_every_agent_mutation_actor(harness):
    c, url, _ = harness
    a = login_headers(c, 1) | {'X-Agent-Id': '2'}
    b = login_headers(c, 2) | {'X-Agent-Id': '1'}
    assert c.get('/auth/me', headers=a).json()['id'] == 1
    assert c.get('/auth/me', headers=a | {'X-Agent-Id': 'garbage'}).status_code == 200
    r = c.post('/tickets', headers=a, json={'body':'Test description', 'subject': 'Auth actors', 'customer_email': 'customer@example.com'})
    assert r.status_code == 201
    p = f'/tickets/{r.json()["id"]}'
    assert c.post(p+'/claim', headers=a).json()['assignee_id'] == 1
    assert c.post(p+'/messages', headers=b, json={'body': 'Impersonation refused'}).status_code == 409
    for suffix, body in [('/notes', {'body': 'Private'}), ('/messages', {'body': 'Answer'}),
                         ('/messages', {'body': 'Internal', 'visibility': 'internal'}),
                         ('/priority', {'priority': 'urgent'})]:
        assert c.post(p+suffix, headers=a, json=body).status_code < 300
    for status, body in [('waiting_on_customer', 'Question'), ('open', None), ('resolved', None)]:
        version = c.get(p, headers=a).json()['version']
        assert c.post(p+'/status', headers=a, json={'status': status, 'body': body, 'version': version}).status_code == 200
    assert c.post(p+'/agent-reopen', headers=a).status_code == 200
    assert c.post(p+'/reassign', headers=a, json={'assignee_id': 2}).status_code == 200
    with psycopg.connect(url) as db:
        assert {r[0] for r in db.execute('SELECT actor FROM events')} == {'agent:1'}
        assert {r[0] for r in db.execute("SELECT agent_id FROM public_messages WHERE author_type='agent'")} == {1}
        assert {r[0] for r in db.execute('SELECT agent_id FROM internal_notes')} == {1}


def test_capability_and_sweep_isolation(harness, agent_headers):
    c, _, _ = harness
    t = c.post('/customer/tickets', json={'body':'Test description', 'subject': 'Customer', 'customer_email': 'c@example.com'}).json()
    customer = {'X-Customer-Token': t['customer_token']}
    for headers in [agent_headers, {'Authorization': 'Bearer test-sweep-secret'}, {}]:
        for path in ['/customer/tickets', f'/customer/tickets/{t["id"]}', '/export.csv']:
            assert c.get(path, headers=headers).status_code == 401
        for suffix in ['/customer-reply', '/reopen']:
            assert c.post(f'/tickets/{t["id"]}'+suffix, headers=headers, json={'body': 'Answer'}).status_code == 401
    for headers in [agent_headers, customer, {}]:
        assert c.post('/admin/sweep', headers=headers).status_code == 401
    assert c.get('/agents', headers=customer).status_code == 401
    # A session copied into the capability header also cannot become a capability.
    response = c.get('/customer/tickets', headers={'X-Customer-Token': agent_headers['Authorization'][7:]})
    assert response.status_code == 401 and response.json() == {'detail':'Customer access token invalid'}


def test_secrets_absent_from_dump_logs_errors_and_other_responses(harness, caplog):
    c, url, _ = harness
    caplog.set_level(logging.DEBUG)
    response = signin(c)
    token = response.json()['token']
    headers = {'Authorization': 'Bearer '+token}
    responses = [c.get('/auth/me', headers=headers), c.get('/agents', headers=headers),
                 c.get('/tickets?assignee=all', headers=headers),
                 c.post('/auth/login', json={'email': [], 'password': TEST_PASSWORD}),
                 signin(c, password=TEST_PASSWORD+'wrong'), c.post('/auth/logout', headers=headers),
                 c.get('/auth/me', headers=headers)]
    for result in responses:
        assert token not in result.text and TEST_PASSWORD not in result.text
    with psycopg.connect(url) as db:
        tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()").fetchall()
        dump = '\n'.join(str(db.execute(sql.SQL('SELECT to_jsonb(t) FROM {} t').format(sql.Identifier(table))).fetchall()) for (table,) in tables)
        assert token not in dump and TEST_PASSWORD not in dump
        sessions = db.execute('SELECT * FROM agent_sessions').fetchall()
        assert sessions and all(token not in str(column) for row in sessions for column in row)
        assert db.execute('SELECT token_hash FROM agent_sessions').fetchone()[0] == token_hash(token)
    assert token not in caplog.text and TEST_PASSWORD not in caplog.text
    logs = [json.loads(r.message) for r in caplog.records if r.name == 'frontdesk.auth']
    assert logs and logs[0]['outcome'] == 'failed'


def test_password_salt_compare_and_provisioning(harness):
    c, url, _ = harness
    first, second = hash_password(TEST_PASSWORD), hash_password(TEST_PASSWORD)
    assert first != second and verify_password(TEST_PASSWORD, first)
    assert not verify_password('wrong', first)
    old = login_headers(c, 1)
    with psycopg.connect(url) as db:
        set_password(db, ' MEERA@ARVO.EXAMPLE ', TEST_PASSWORD+'new')
    assert c.get('/auth/me', headers=old).status_code == 401
    assert signin(c).status_code == 401
    assert signin(c, password=TEST_PASSWORD+'new').status_code == 200


def test_demo_credentials_only_when_enabled(harness, monkeypatch):
    c, url, _ = harness
    password = 'demo-special-<&-secret'
    monkeypatch.setenv('FRONTDESK_DEMO_PASSWORD', password)
    monkeypatch.setenv('FRONTDESK_SEED_DEMO', 'false')
    assert password not in c.get('/').text and 'meera@arvo.example' not in c.get('/').text
    with psycopg.connect(url, row_factory=dict_row) as db:
        db.execute('UPDATE agents SET password_hash=NULL')
        seed(db)
        assert not any(r['password_hash'] for r in db.execute('SELECT password_hash FROM agents'))
    monkeypatch.setenv('FRONTDESK_SEED_DEMO', 'true')
    page = c.get('/').text
    assert 'demo-special-&lt;&amp;-secret' in page and 'divya@arvo.example' in page
    with psycopg.connect(url, row_factory=dict_row) as db:
        seed(db)
        before = db.execute('SELECT password_hash FROM agents ORDER BY id').fetchall()
        assert sum(r['password_hash'] is not None for r in before) == 3
        seed(db)
        assert db.execute('SELECT password_hash FROM agents ORDER BY id').fetchall() == before
    for name in ['meera', 'arun', 'divya']:
        assert signin(c, name+'@arvo.example', password).status_code == 200
    assert signin(c, 'sneha@arvo.example', password).status_code == 401
    monkeypatch.delenv('FRONTDESK_DEMO_PASSWORD')
    with psycopg.connect(url, row_factory=dict_row) as db, pytest.raises(ValueError, match='FRONTDESK_DEMO_PASSWORD'):
        seed(db)


def test_restricted_runtime_can_authenticate_but_cannot_edit_audit(harness):
    from scripts.provision_runtime import provision, verify_runtime
    _c, url, _ = harness
    role = 'auth_test_'+uuid4().hex
    try:
        runtime_url = provision(url, 'temporary-runtime-password', role=role)
        proof = verify_runtime(runtime_url)
        assert proof['role'] == role and not proof['events_update_delete_truncate']
        assert proof['event_triggers'] == ['events_immutable', 'events_no_truncate', 'events_server_timestamp']
        with TestClient(create_app(runtime_url, sweep_interval=0)) as restricted:
            assert signin(restricted, password='wrong').status_code == 401
            headers = login_headers(restricted, 1)
            assert restricted.get('/auth/me', headers=headers).status_code == 200
            ticket = restricted.post('/tickets', headers=headers, json={'body':'Test description', 'subject': 'Runtime', 'customer_email': 'x@example.com'})
            assert ticket.status_code == 201
            assert restricted.post('/auth/logout', headers=headers).status_code == 200
        for statement in ['UPDATE events SET actor=\'forged\'', 'DELETE FROM events', 'TRUNCATE events', 'UPDATE agents SET password_hash=NULL']:
            with psycopg.connect(runtime_url) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)
        with psycopg.connect(runtime_url) as db:
            db.execute("SELECT set_config('frontdesk.seeding','on',true)")
            before = db.execute('SELECT clock_timestamp()').fetchone()[0]
            row = db.execute("INSERT INTO events(ticket_id,actor,event_type,created_at) VALUES (%s,'system','created','2000-01-01') RETURNING created_at", (ticket.json()['id'],)).fetchone()
            after = db.execute('SELECT clock_timestamp()').fetchone()[0]
            assert row[0].year != 2000 and before <= row[0] <= after
    finally:
        with psycopg.connect(url, autocommit=True) as db:
            if db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                db.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                db.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_login_ui_session_lifecycle():
    import subprocess
    result = subprocess.run(['node', 'tests/ui_auth.cjs'], text=True, capture_output=True, check=True)
    assert result.stdout.strip() == 'Login UI lifecycle passed'


def test_concurrent_failed_logins_share_one_database_counter(auth_harness, caplog):
    from tests.test_concurrency import parallel
    c, url, _ = auth_harness
    responses = parallel(c, [lambda client: signin(client, password='wrong') for _ in range(6)])
    assert sorted(r.status_code for r in responses) == [401]*5 + [429]
    with psycopg.connect(url) as db:
        assert db.execute('SELECT failures FROM agent_login_attempts').fetchone()[0] == 5
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 0
    outcomes = [json.loads(r.message)['outcome'] for r in caplog.records if r.name == 'frontdesk.auth']
    assert sorted(outcomes) == ['failed']*5 + ['throttled']


def test_repeated_provisioning_with_non_superuser_owner(api_db):
    """Model Render's CREATEROLE owner, including the second deployment."""
    from psycopg.conninfo import make_conninfo

    from scripts.provision_runtime import provision
    owner = 'bootstrap_test_'+uuid4().hex
    role = 'runtime_test_'+uuid4().hex
    try:
        with psycopg.connect(api_db) as db:
            original, database, schema = db.execute('SELECT current_user,current_database(),current_schema()').fetchone()
            db.execute(sql.SQL('CREATE ROLE {} LOGIN CREATEROLE PASSWORD {}').format(sql.Identifier(owner), sql.Literal('bootstrap-test-password')))
            db.execute(sql.SQL('GRANT CONNECT, CREATE ON DATABASE {} TO {} WITH GRANT OPTION').format(sql.Identifier(database), sql.Identifier(owner)))
            db.execute(sql.SQL('ALTER SCHEMA {} OWNER TO {}').format(sql.Identifier(schema), sql.Identifier(owner)))
            for (table,) in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()').fetchall():
                db.execute(sql.SQL('ALTER TABLE {} OWNER TO {}').format(sql.Identifier(table), sql.Identifier(owner)))
        owner_url = make_conninfo(api_db, user=owner, password='bootstrap-test-password')
        provision(owner_url, 'runtime-test-password', role=role)
        runtime_url = provision(owner_url, 'runtime-test-password', role=role)
        with psycopg.connect(runtime_url) as db:
            assert db.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit FROM pg_roles WHERE rolname=current_user').fetchone() == (False,False,False,False)
            assert db.execute("SELECT has_table_privilege(current_user,'events','UPDATE'),has_table_privilege(current_user,'events','DELETE')").fetchone() == (False,False)
            db.execute('SELECT count(*) FROM agents')
    finally:
        with psycopg.connect(api_db, autocommit=True) as db:
            if db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (owner,)).fetchone():
                if db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                    db.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(owner)))
                    db.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM {} CASCADE').format(sql.Identifier(database), sql.Identifier(role)))
                    db.execute('RESET ROLE')
                db.execute(sql.SQL('REASSIGN OWNED BY {} TO {}').format(sql.Identifier(owner), sql.Identifier(original)))
            for name in [role, owner]:
                if db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (name,)).fetchone():
                    db.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(name)))
                    db.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
