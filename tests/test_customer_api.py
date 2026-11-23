from uuid import uuid4

import psycopg
from fastapi.routing import APIRoute


def headers(ticket):
    return {"X-Customer-Token": str(ticket["customer_token"])}


def test_customer_allowlist_views_and_csv(harness, seeded_ticket):
    client, url, _ = harness
    with psycopg.connect(url) as db:
        db.execute("INSERT INTO public_messages(ticket_id, author_type, body) VALUES (%s, 'customer', 'Public question')", (seeded_ticket["id"],))
    response = client.get(f'/customer/tickets/{seeded_ticket["id"]}', headers=headers(seeded_ticket))
    assert response.status_code == 200
    assert set(response.json()) == {"id", "subject", "priority", "status", "created_at", "start_at", "first_replied_at", "resolved_at", "closed_at", "previous_ticket_id", "messages"}
    assert response.json()["messages"][0]["body"] == "Public question"
    assert "agent_id" not in response.text
    assert client.get("/customer/tickets", headers=headers(seeded_ticket)).json()[0]["id"] == seeded_ticket["id"]
    exported = client.get("/export.csv", headers=headers(seeded_ticket))
    assert exported.status_code == 200
    assert exported.text.splitlines()[0] == "id,subject,description,priority,status,created_at,previous_ticket_id"
    assert "Printer offline" in exported.text


def test_customer_access_is_scoped(harness, seeded_ticket):
    client, _, _ = harness
    path = f'/customer/tickets/{seeded_ticket["id"]}'
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Customer-Token": str(uuid4())}).status_code == 404
    assert client.get("/customer/tickets", headers={"X-Customer-Token": str(uuid4())}).json() == []


def test_csv_neutralizes_formula_injection(harness, seeded_ticket):
    client, url, _ = harness
    with psycopg.connect(url) as db:
        db.execute("UPDATE tickets SET subject = '=HYPERLINK(1)' WHERE id = %s", (seeded_ticket["id"],))
    assert "'=HYPERLINK(1)" in client.get("/export.csv", headers=headers(seeded_ticket)).text


def test_internal_note_marker_never_leaks(harness, seeded_ticket, agent_headers):
    client, url, _ = harness
    marker = "PRIVATE_NOTE_" + uuid4().hex
    ticket_id = seeded_ticket["id"]
    result = client.post(f"/tickets/{ticket_id}/notes", json={"body": marker}, headers=agent_headers)
    assert result.status_code == 201
    # Explicit inventory must be expanded whenever a customer read route is added.
    paths = {"/customer/tickets", "/customer/tickets/{ticket_id}", "/export.csv"}
    registered = {route.path for route in client.app.routes if isinstance(route, APIRoute)
                  and "GET" in route.methods and (route.path.startswith("/customer/") or route.path == "/export.csv")}
    assert paths == registered
    for path in paths:
        response = client.get(path.replace("{ticket_id}", str(ticket_id)), headers=headers(seeded_ticket))
        assert response.status_code == 200
        assert marker not in response.text
        assert "internal_notes" not in response.text
        assert "customer_token" not in response.text
    assert client.post(f"/tickets/{ticket_id}/notes", json={"body": marker}, headers=headers(seeded_ticket)).status_code == 401
    with psycopg.connect(url) as db:
        assert db.execute("SELECT body FROM internal_notes WHERE ticket_id = %s", (ticket_id,)).fetchone()[0] == marker
        events = db.execute("SELECT event_type, before_value, after_value FROM events").fetchall()
        assert len(events) == 1
        assert events[0][0] == "internal_note_added"
        assert marker not in str(events)
        assert "body" not in str(events)


def test_audit_writer_refuses_note_body(harness, seeded_ticket):
    import pytest

    from frontdesk.events import log_event
    _, url, _ = harness
    with psycopg.connect(url) as db:
        with pytest.raises(ValueError, match="Unexpected audit metadata"):
            log_event(db, seeded_ticket["id"], "agent:1", "internal_note_added", after={"body": "secret"})
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_message_note_leak_and_customer_reply(harness, seeded_ticket, agent_headers):
    client, url, _ = harness
    marker = "INTERNAL_" + uuid4().hex
    path = f'/tickets/{seeded_ticket["id"]}'
    assert client.post(path + '/messages', headers=agent_headers, json={"visibility": "internal", "body": marker}).status_code == 201
    reply = client.post(path + '/customer-reply', headers=headers(seeded_ticket), json={"body": "Public follow-up"})
    assert reply.status_code == 201
    assert marker not in reply.text
    for endpoint in ["/customer/tickets", f'/customer/tickets/{seeded_ticket["id"]}', "/export.csv"]:
        response = client.get(endpoint, headers=headers(seeded_ticket))
        assert response.status_code == 200
        assert marker not in response.text
    with psycopg.connect(url) as db:
        assert marker not in str(db.execute("SELECT before_value, after_value FROM events").fetchall())


def test_complete_customer_route_inventory_and_note_leak_lifecycle(harness, agent_headers):
    from datetime import timedelta

    from tests.test_mutations import create
    client, url, now = harness
    ticket = create(client, agent_headers)
    ticket_id = ticket["id"]
    assert client.post(f'/tickets/{ticket_id}/claim', headers=agent_headers).status_code == 200
    access = {"X-Customer-Token": ticket["customer_token"]}
    marker = "NEVER_PUBLIC_" + uuid4().hex
    assert client.post(f'/tickets/{ticket_id}/messages', headers=agent_headers, json={"visibility": "internal", "body": marker}).status_code == 201
    expected = {
        ("POST", "/customer/tickets"),
        ("GET", "/customer/tickets"), ("GET", "/customer/tickets/{ticket_id}"),
        ("GET", "/export.csv"), ("POST", "/tickets/{ticket_id}/customer-reply"),
        ("POST", "/tickets/{ticket_id}/reopen"),
    }
    registered = {(method, route.path) for route in client.app.routes if isinstance(route, APIRoute)
                  and "customer" in route.tags for method in route.methods}
    assert registered == expected
    called = {("POST", "/customer/tickets")}
    def read_all(ids):
        for method, template in expected:
            if method != "GET":
                continue
            paths = [template.replace("{ticket_id}", str(ident)) for ident in ids] if "{ticket_id}" in template else [template]
            for path in paths:
                response = client.get(path, headers=access)
                assert response.status_code == 200
                assert marker not in response.text
                assert "customer_token" not in response.text
            called.add((method, template))
    response = client.post(f'/tickets/{ticket_id}/customer-reply', headers=access, json={"body": "Customer reply"})
    assert response.status_code == 201
    assert marker not in response.text
    called.add(("POST", "/tickets/{ticket_id}/customer-reply"))
    read_all([ticket_id])
    assert client.post(f'/tickets/{ticket_id}/status', headers=agent_headers, json={"version": client.get((f'/tickets/{ticket_id}/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), "status": "resolved"}).status_code == 200
    reopened = client.post(f'/tickets/{ticket_id}/reopen', headers=access)
    assert reopened.status_code == 200
    assert marker not in reopened.text
    called.add(("POST", "/tickets/{ticket_id}/reopen"))
    read_all([ticket_id])
    assert client.post(f'/tickets/{ticket_id}/status', headers=agent_headers, json={"version": client.get((f'/tickets/{ticket_id}/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), "status": "resolved"}).status_code == 200
    now[0] += timedelta(days=9)
    linked = client.post(f'/tickets/{ticket_id}/reopen', headers=access)
    assert linked.status_code == 201
    assert marker not in linked.text
    read_all([ticket_id, linked.json()["ticket"]["id"]])
    assert called == registered
    with psycopg.connect(url) as db:
        assert marker not in str(db.execute("SELECT before_value, after_value FROM events").fetchall())
        assert db.execute("SELECT body FROM internal_notes").fetchone()[0] == marker
    # Customers cannot read an agent thread, queue or event stream.
    for path in ["/tickets", f'/tickets/{ticket_id}', f'/tickets/{ticket_id}/events', '/agents']:
        assert client.get(path, headers=access).status_code == 401
