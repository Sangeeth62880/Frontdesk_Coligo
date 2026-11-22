import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from frontdesk.api import create_app
from frontdesk.scheduler import Sweeper
from scripts.seed_demo import seed


def test_static_shells_and_health(harness):
    client, _, _ = harness
    for path in ['/', '/customer', '/static/app.js', '/static/customer.js', '/static/style.css']:
        result = client.get(path)
        assert result.status_code == 200
        assert result.headers['x-content-type-options'] == 'nosniff'
    assert 'frontdesk-key' not in client.get('/static/customer.js').text
    assert 'internal_notes' not in client.get('/customer').text
    assert client.get('/health').json() == {'status': 'ok'}


def test_demo_cases_are_idempotent_and_include_all_states(api_db):
    with psycopg.connect(api_db, row_factory=dict_row) as db:
        first = seed(db)
        assert len(first) == 4
        assert seed(db) == first
        rows = db.execute('SELECT * FROM tickets ORDER BY id').fetchall()
        assert {r['status'] for r in rows} == {'open', 'waiting_on_customer', 'resolved'}
        assert any(r['assignee_id'] is None for r in rows)
        assert db.execute('SELECT count(*) AS n FROM internal_notes').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM events').fetchone()['n'] > 4


def test_scheduler_closes_waiting_without_endpoint_call(api_db):
    with psycopg.connect(api_db, row_factory=dict_row) as db:
        ticket = db.execute("INSERT INTO tickets(subject,customer_email,priority,status,start_at) VALUES ('Old wait','old@example.com','small','waiting_on_customer','2026-11-02 10:00+05:30') RETURNING id").fetchone()
        cycle = db.execute("INSERT INTO resolution_cycles(ticket_id,cycle_number,opened_at,start_at) VALUES (%s,1,'2026-11-02 10:00+05:30','2026-11-02 10:00+05:30') RETURNING id", (ticket['id'],)).fetchone()
        db.execute("INSERT INTO ticket_pauses(ticket_id,cycle_id,paused_at) VALUES (%s,%s,'2026-11-02 11:00+05:30')", (ticket['id'],cycle['id']))
    sweeper = Sweeper(api_db, .05)
    try:
        sweeper.start()
        assert sweeper.first_success.wait(timeout=5)
    finally:
        sweeper.stop()
    with psycopg.connect(api_db) as db:
        assert db.execute('SELECT status FROM tickets').fetchone()[0] == 'closed'
        assert db.execute("SELECT count(*) FROM events WHERE event_type='auto_closed' AND actor='system'").fetchone()[0] == 1


def test_app_lifespan_starts_and_stops_sweeper(api_db, monkeypatch):
    calls=[]
    class FakeSweeper:
        def __init__(self, url, interval):
            assert url == api_db
            assert interval == 10
        def start(self): calls.append('start')
        def stop(self): calls.append('stop')
    monkeypatch.setattr('frontdesk.api.Sweeper', FakeSweeper)
    with TestClient(create_app(api_db, sweep_interval=10)) as client:
        assert client.get('/').status_code == 200
        assert calls == ['start']
    assert calls == ['start','stop']
