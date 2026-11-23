from datetime import datetime, timedelta
from uuid import uuid4

import psycopg

from frontdesk.business_time import Calendar
from tests.test_mutations import create, event_types


def reopen_at(harness, agent_headers, minutes):
    client, url, now = harness
    ticket = create(client, agent_headers, "urgent")
    # Resolve after its urgent end-of-day deadline to preserve a real breach.
    now[0] += timedelta(days=1)
    path = f'/tickets/{ticket["id"]}'
    assert client.post(path+'/claim', headers=agent_headers).status_code == 200
    assert client.post(path + '/status', headers=agent_headers, json={"version": client.get((path + '/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), "status": "resolved"}).status_code == 200
    with psycopg.connect(url) as db:
        calendar = Calendar(frozenset(row[0] for row in db.execute("SELECT day FROM holidays")))
    now[0] = calendar.add(now[0], minutes)
    return ticket


def test_exact_2700_reopens_new_cycle_preserving_breach_event(harness, agent_headers):
    client, url, now = harness
    ticket = reopen_at(harness, agent_headers, 2700)
    old_events = event_types(client, ticket["id"], agent_headers)
    assert old_events[-1]["after_value"]["breached"] is True
    with psycopg.connect(url) as db:
        old_cycle = db.execute("SELECT * FROM resolution_cycles").fetchone()
    response = client.post(f'/tickets/{ticket["id"]}/reopen', headers={"X-Customer-Token": ticket["customer_token"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "reopen"
    assert body["ticket"]["id"] == ticket["id"]
    assert body["sla"]["cycle_number"] == 2
    assert body["sla"]["resolution_breached"] is True
    assert body["sla"]["is_late"] is True
    assert datetime.fromisoformat(body["sla"]["resolution_due_at"]) > now[0]
    new_events = event_types(client, ticket["id"], agent_headers)
    assert new_events[:-1] == old_events
    assert new_events[-1]["event_type"] == "reopened"
    assert new_events[-1]["actor"] == "customer"
    with psycopg.connect(url) as db:
        cycles = db.execute("SELECT * FROM resolution_cycles ORDER BY cycle_number").fetchall()
        assert len(cycles) == 2
        assert cycles[0] == old_cycle
        assert db.execute("SELECT start_at FROM tickets").fetchone()[0] == datetime.fromisoformat(ticket["start_at"])


def test_2701_creates_linked_ticket(harness, agent_headers):
    client, _url, _ = harness
    old = reopen_at(harness, agent_headers, 2701)
    headers = {"X-Customer-Token": old["customer_token"]}
    original_events = event_types(client, old["id"], agent_headers)
    response = client.post(f'/tickets/{old["id"]}/reopen', headers=headers)
    assert response.status_code == 201
    result = response.json()
    assert result["action"] == "linked_new_ticket"
    assert result["ticket"]["id"] != old["id"]
    assert result["ticket"]["previous_ticket_id"] == old["id"]
    assert result["ticket"]["priority"] == "urgent"
    assert result["sla"]["cycle_number"] == 1
    assert event_types(client, old["id"], agent_headers) == original_events
    assert event_types(client, result["ticket"]["id"], agent_headers)[0]["event_type"] == "created"
    assert len(client.get('/customer/tickets', headers=headers).json()) == 2


def test_reopen_does_not_reset_first_reply_or_use_old_pauses(harness, agent_headers):
    client, url, now = harness
    ticket = create(client, agent_headers)
    path = f'/tickets/{ticket["id"]}'
    assert client.post(path + "/claim", headers=agent_headers).status_code == 200
    assert client.post(path + '/messages', headers=agent_headers, json={"body": "First reply"}).status_code == 201
    assert client.post(path + '/status', headers=agent_headers, json={"version": client.get((path + '/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), "status": "waiting_on_customer", "body": "Please reply"}).status_code == 200
    now[0] += timedelta(hours=1)
    assert client.post(path + '/status', headers=agent_headers, json={"version": client.get((path + '/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), "status": "resolved"}).status_code == 200
    replied = client.get(path, headers=agent_headers).json()["first_replied_at"]
    now[0] += timedelta(hours=1)
    response = client.post(path + '/reopen', headers={"X-Customer-Token": ticket["customer_token"]})
    assert response.status_code == 200
    from frontdesk.business_time import Policy, deadlines
    with psycopg.connect(url) as db:
        calendar = Calendar(frozenset(row[0] for row in db.execute("SELECT day FROM holidays")))
        assert db.execute("SELECT count(*) FROM ticket_pauses").fetchone()[0] == 1
    assert datetime.fromisoformat(response.json()["sla"]["resolution_due_at"]) == deadlines(calendar, now[0], Policy(270, 1620))[1]
    assert client.get(path, headers=agent_headers).json()["first_replied_at"] == replied


def test_reopen_auth_and_active_ticket_conflict(harness, agent_headers):
    client, _, _ = harness
    ticket = create(client, agent_headers)
    path = f'/tickets/{ticket["id"]}/reopen'
    assert client.post(path).status_code == 401
    assert client.post(path, headers={"X-Customer-Token": str(uuid4())}).status_code == 401
    assert client.post(path, headers={"X-Customer-Token": ticket["customer_token"]}).status_code == 409


def test_parallel_reopen_creates_one_cycle(harness, agent_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient
    client, url, _ = harness
    ticket = reopen_at(harness, agent_headers, 1)
    barrier = Barrier(2)
    def reopen(_):
        with TestClient(client.app) as other:
            barrier.wait(timeout=5)
            return other.post(f'/tickets/{ticket["id"]}/reopen', headers={"X-Customer-Token": ticket["customer_token"]}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reopen, [1, 2])) == [200, 409]
    with psycopg.connect(url) as db:
        assert db.execute("SELECT count(*) FROM resolution_cycles").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM events WHERE event_type = 'reopened'").fetchone()[0] == 1
