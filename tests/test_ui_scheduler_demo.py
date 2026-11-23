import psycopg
import pytest
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
        assert len(first) == 8
        assert seed(db) == first
        rows = db.execute('SELECT * FROM tickets ORDER BY id').fetchall()
        assert {r['status'] for r in rows} == {'open', 'waiting_on_customer', 'resolved', 'closed'}
        assert any(r['assignee_id'] is None for r in rows)
        assert db.execute('SELECT count(*) AS n FROM internal_notes').fetchone()['n'] == 2
        assert db.execute('SELECT count(*) AS n FROM events').fetchone()['n'] > 8


def test_seed_timelines_match_messages_starts_and_event_history(api_db):
    from frontdesk import service
    from frontdesk.business_time import deadlines
    with psycopg.connect(api_db, row_factory=dict_row) as db:
        ids = seed(db)
        now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
        rows = db.execute('SELECT * FROM tickets ORDER BY id').fetchall()
        assert len(ids) == len(rows) == 8
        assert {row['assignee_id'] for row in rows} == {None,1,2,3}
        for ticket in rows:
            events = db.execute('SELECT * FROM events WHERE ticket_id=%s ORDER BY id',(ticket['id'],)).fetchall()
            times = [event['created_at'] for event in events]
            assert times == sorted(times) and all(ticket['created_at'] <= stamp <= now for stamp in times)
            messages = db.execute('SELECT * FROM public_messages WHERE ticket_id=%s ORDER BY created_at,id',(ticket['id'],)).fetchall()
            assert messages[0]['author_type'] == 'customer' and messages[0]['created_at'] == ticket['created_at']
            assert all(ticket['created_at'] <= message['created_at'] <= now for message in messages)
            agent = [message for message in messages if message['author_type']=='agent']
            assert ticket['first_replied_at'] == (agent[0]['created_at'] if agent else None)
            public_events = [event for event in events if event['event_type']=='public_reply' and event['actor'].startswith('agent:')]
            if agent:
                assert public_events[0]['created_at'] == agent[0]['created_at']
            calendar, policy = service.calendar_and_policy(db,ticket['priority'])
            assert ticket['start_at'] == calendar.start(ticket['created_at'])
            assert ticket['first_reply_due_at'] == deadlines(calendar,ticket['start_at'],policy)[0]
            cycles = db.execute('SELECT * FROM resolution_cycles WHERE ticket_id=%s',(ticket['id'],)).fetchall()
            assert len(cycles)==1 and cycles[0]['opened_at']==ticket['created_at'] and cycles[0]['start_at']==ticket['start_at']
            for pause in db.execute('SELECT * FROM ticket_pauses WHERE ticket_id=%s',(ticket['id'],)):
                assert ticket['created_at'] <= pause['paused_at'] <= now
                assert pause['resumed_at'] is None or pause['paused_at'] <= pause['resumed_at'] <= now
            for note in db.execute('SELECT * FROM internal_notes WHERE ticket_id=%s',(ticket['id'],)):
                assert ticket['created_at'] <= note['created_at'] <= now
        db.execute("SELECT set_config('frontdesk.seeding','on',true)")
        for statement in ('UPDATE events SET actor=\'changed\'','DELETE FROM events','TRUNCATE events'):
            with pytest.raises(psycopg.errors.RaiseException), db.transaction():
                db.execute(statement)


def test_only_owner_with_seed_setting_can_supply_event_time(api_db):
    with psycopg.connect(api_db, row_factory=dict_row) as db:
        ticket = db.execute("INSERT INTO tickets(subject,customer_email,priority,start_at) VALUES ('Seed guard','guard@example.com','small',clock_timestamp()) RETURNING id").fetchone()
        def insert():
            return db.execute("INSERT INTO events(ticket_id,actor,event_type,created_at) VALUES (%s,'system','created','2000-01-01') RETURNING created_at",(ticket['id'],)).fetchone()['created_at']
        assert insert().year != 2000
        db.execute("SELECT set_config('frontdesk.seeding','on',true)")
        assert insert().year == 2000
        db.execute("SELECT set_config('frontdesk.seeding','off',true)")
        assert insert().year != 2000


def test_seed_rejects_future_actual_history(api_db):
    from datetime import timedelta

    from scripts.seed_demo import seed_cases
    with psycopg.connect(api_db, row_factory=dict_row) as db:
        future = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']+timedelta(days=1)
        with pytest.raises(ValueError,match='future'):
            seed_cases(db,future)
        assert db.execute('SELECT count(*) AS n FROM tickets').fetchone()['n'] == 0


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
