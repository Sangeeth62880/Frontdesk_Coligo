from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import psycopg
from fastapi.testclient import TestClient

from frontdesk.business_time import Calendar
from tests.test_mutations import create, event_types

SWEEP = {"Authorization": "Bearer test-sweep-secret"}


def wait(client, ticket, agent_headers):
    assert client.post(f'/tickets/{ticket["id"]}/claim', headers=agent_headers).status_code == 200
    result = client.post(f'/tickets/{ticket["id"]}/status', headers=agent_headers, json={"version": client.get((f'/tickets/{ticket["id"]}/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), "status": "waiting_on_customer", "body": "Please reply"})
    assert result.status_code == 200


def threshold(url, start):
    with psycopg.connect(url) as db:
        calendar = Calendar(frozenset(row[0] for row in db.execute("SELECT day FROM holidays")))
    return calendar.add(start, 2700)


def test_sweep_threshold_and_idempotency(harness, agent_headers):
    client, url, now = harness
    ticket = create(client, agent_headers, "urgent")
    wait(client, ticket, agent_headers)
    due = threshold(url, now[0])
    now[0] = due - timedelta(minutes=1)
    assert client.post('/admin/sweep', headers=SWEEP).json()["closed_count"] == 0
    now[0] = due
    response = client.post('/admin/sweep', headers=SWEEP)
    assert response.status_code == 200
    assert response.json() == {"closed_count": 1, "ticket_ids": [ticket["id"]]}
    assert client.post('/admin/sweep', headers=SWEEP).json()["closed_count"] == 0
    events = event_types(client, ticket["id"], agent_headers)
    closed = [event for event in events if event["event_type"] == "auto_closed"]
    assert len(closed) == 1
    assert closed[0]["actor"] == "system"
    assert closed[0]["after_value"]["breached"] is False
    with psycopg.connect(url) as db:
        assert db.execute("SELECT status FROM tickets").fetchone()[0] == "closed"
        assert db.execute("SELECT count(*) FROM ticket_pauses WHERE resumed_at IS NULL").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM resolution_cycles WHERE ended_at IS NULL").fetchone()[0] == 0


def test_parallel_sweeps_write_one_close_event(harness, agent_headers):
    client, url, now = harness
    ticket = create(client, agent_headers)
    wait(client, ticket, agent_headers)
    now[0] = threshold(url, now[0])
    barrier = Barrier(2)
    def sweep(_):
        with TestClient(client.app) as parallel:
            barrier.wait(timeout=5)
            response = parallel.post('/admin/sweep', headers=SWEEP)
            assert response.status_code == 200
            return response.json()["closed_count"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(sweep, [1, 2]))
    assert sorted(counts) == [0, 1]
    assert len([event for event in event_types(client, ticket["id"], agent_headers) if event["event_type"] == "auto_closed"]) == 1


def test_sweep_requires_separate_secret(harness, agent_headers):
    client, _, _ = harness
    assert client.post('/admin/sweep').status_code == 401
    assert client.post('/admin/sweep', headers=agent_headers).status_code == 401


def test_pause_after_breach_stays_breached_on_autoclose(harness, agent_headers):
    client, url, now = harness
    ticket = create(client, agent_headers, "urgent")
    now[0] += timedelta(days=1)
    wait(client, ticket, agent_headers)
    now[0] = threshold(url, now[0])
    assert client.post('/admin/sweep', headers=SWEEP).json()["closed_count"] == 1
    closed = event_types(client, ticket["id"], agent_headers)[-1]
    assert closed["event_type"] == "auto_closed"
    assert closed["after_value"]["breached"] is True
