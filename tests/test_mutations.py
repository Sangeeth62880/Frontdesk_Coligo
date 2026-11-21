from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from frontdesk.business_time import ZONE


def create(client, agent_headers, priority="medium"):
    response = client.post('/tickets', headers=agent_headers, json={"subject": "Checkout fails", "customer_email": "customer@example.com", "priority": priority})
    assert response.status_code == 201, response.text
    return response.json()


def event_types(client, ticket_id, agent_headers):
    response = client.get(f'/tickets/{ticket_id}/events', headers=agent_headers)
    assert response.status_code == 200
    return response.json()


def test_first_reply_only_first_public_agent_message(harness, agent_headers):
    client, url, now = harness
    ticket = create(client, agent_headers)
    path = f'/tickets/{ticket["id"]}'
    customer = {"X-Customer-Token": ticket["customer_token"]}
    assert client.post(path + '/customer-reply', headers=customer, json={"body": "More details"}).status_code == 201
    assert client.post(path + '/messages', headers=agent_headers, json={"body": "Private investigation", "visibility": "internal"}).status_code == 201
    assert client.get(path, headers=agent_headers).json()["first_replied_at"] is None
    assert client.post(path + "/claim", headers=agent_headers).status_code == 200
    first = now[0]
    assert client.post(path + '/messages', headers=agent_headers, json={"body": "Working on it"}).status_code == 201
    now[0] += timedelta(hours=1)
    assert client.post(path + '/messages', headers=agent_headers, json={"body": "Update"}).status_code == 201
    view = client.get(path, headers=agent_headers).json()
    from datetime import datetime
    assert datetime.fromisoformat(view["first_replied_at"]) == first
    assert view["internal_notes"][0]["visibility"] == "internal"
    assert len(view["messages"]) == 3
    assert [event["event_type"] for event in event_types(client, ticket["id"], agent_headers)] == ["created", "public_reply", "internal_note_added", "claimed", "public_reply", "public_reply"]


def test_waiting_resumes_and_preserves_pause_history(harness, agent_headers):
    client, url, now = harness
    ticket = create(client, agent_headers, "urgent")
    path = f'/tickets/{ticket["id"]}'
    now[0] = now[0].replace(hour=11)
    assert client.post(path + '/status', headers=agent_headers, json={"status": "waiting_on_customer"}).status_code == 200
    # Same status is a no-op and creates no second pause/event.
    assert client.post(path + '/status', headers=agent_headers, json={"status": "waiting_on_customer"}).status_code == 200
    now[0] = now[0].replace(hour=12)
    assert client.post(path + '/customer-reply', headers={"X-Customer-Token": ticket["customer_token"]}, json={"body": "Here is the answer"}).status_code == 201
    view = client.get(path, headers=agent_headers).json()
    assert view["status"] == "open"
    from datetime import datetime
    assert datetime.fromisoformat(view["sla"]["resolution_due_at"]).astimezone(ZONE).isoformat() == "2026-11-24T10:30:00+05:30"
    with psycopg.connect(url) as db:
        pauses = db.execute("SELECT paused_at, resumed_at FROM ticket_pauses").fetchall()
        assert len(pauses) == 1
        assert pauses[0][1] - pauses[0][0] == timedelta(hours=1)
    assert [e["event_type"] for e in event_types(client, ticket["id"], agent_headers)] == ["created", "paused", "status_changed", "public_reply", "resumed", "status_changed"]


def test_priority_change_logs_both_deadlines_and_is_immediately_late(harness, agent_headers):
    from datetime import datetime
    client, _, now = harness
    ticket = create(client, agent_headers)
    now[0] += timedelta(days=1)
    response = client.post(f'/tickets/{ticket["id"]}/priority', headers=agent_headers, json={"priority": "urgent"})
    assert response.status_code == 200
    assert response.json()["sla"]["resolution_breached"] is True
    event = event_types(client, ticket["id"], agent_headers)[-1]
    assert event["event_type"] == "priority_changed"
    assert event["before_value"]["priority"] == "medium"
    assert event["after_value"]["priority"] == "urgent"
    assert datetime.fromisoformat(event["before_value"]["resolution_due_at"]) > now[0]
    assert datetime.fromisoformat(event["after_value"]["resolution_due_at"]) < now[0]
    assert "first_reply_due_at" in event["before_value"]
    assert "first_reply_due_at" in event["after_value"]


def test_resolve_snapshots_breach_and_cannot_bypass_reopen(harness, agent_headers):
    client, url, now = harness
    ticket = create(client, agent_headers, "urgent")
    now[0] += timedelta(days=1)
    path = f'/tickets/{ticket["id"]}'
    response = client.post(path + '/status', headers=agent_headers, json={"status": "resolved"})
    assert response.status_code == 200
    event = event_types(client, ticket["id"], agent_headers)[-1]
    assert event["after_value"]["breached"] is True
    assert event["after_value"]["resolution_due_at"]
    assert client.post(path + '/status', headers=agent_headers, json={"status": "open"}).status_code == 409
    assert client.post(path + '/messages', headers=agent_headers, json={"body": "Late"}).status_code == 409
    assert client.post(path + '/priority', headers=agent_headers, json={"priority": "small"}).status_code == 409
    with psycopg.connect(url) as db:
        assert db.execute("SELECT breached FROM resolution_cycles").fetchone()[0] is True


def test_agent_views_require_auth_and_customer_reply_is_scoped(harness, agent_headers):
    client, _, _ = harness
    ticket = create(client, agent_headers)
    other = {"X-Customer-Token": str(uuid4())}
    for path in ['/tickets', f'/tickets/{ticket["id"]}', f'/tickets/{ticket["id"]}/events', '/agents']:
        assert client.get(path, headers={"X-Customer-Token": ticket["customer_token"]}).status_code == 401
    assert client.post(f'/tickets/{ticket["id"]}/customer-reply', headers=other, json={"body": "Unauthorized"}).status_code == 404
    assert client.get('/tickets?assignee=all', headers=agent_headers).json()[0]["id"] == ticket["id"]
    assert client.get('/tickets', headers=agent_headers).json() == []


def test_client_timestamps_rejected_and_server_event_time_used(harness, agent_headers):
    from datetime import datetime, timezone
    client, _, _ = harness
    before = datetime.now(timezone.utc)
    bad = client.post('/tickets', headers=agent_headers, json={"subject": "Test", "customer_email": "a@example.com", "created_at": "2000-01-01T00:00:00Z"})
    assert bad.status_code == 422
    ticket = create(client, agent_headers)
    stamped = datetime.fromisoformat(event_types(client, ticket["id"], agent_headers)[0]["created_at"])
    assert before <= stamped <= datetime.now(timezone.utc)
    bad = client.post(f'/tickets/{ticket["id"]}/messages', headers=agent_headers, json={"body": "Reply", "created_at": "2000-01-01T00:00:00Z"})
    assert bad.status_code == 422


def test_calendar_range_failure_rolls_back_creation(harness, agent_headers):
    client, url, now = harness
    now[0] = now[0].replace(year=2028)
    response = client.post('/tickets', headers=agent_headers, json={"subject": "Out of range", "customer_email": "a@example.com"})
    assert response.status_code == 503
    assert "last seeded holiday" in response.text
    with psycopg.connect(url) as db:
        assert db.execute("SELECT count(*) FROM tickets").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
