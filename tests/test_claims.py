from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.conftest import login_headers


@pytest.mark.parametrize("attempt", range(3))
def test_exactly_one_parallel_claim_wins(harness, seeded_ticket, attempt):
    client, url, _ = harness
    credentials = {i: login_headers(client, i) for i in [1, 2]}
    barrier = Barrier(2)
    def claim(agent_id):
        with TestClient(client.app) as other:
            barrier.wait(timeout=5)
            response = other.post(f'/tickets/{seeded_ticket["id"]}/claim', headers=credentials[agent_id])
            return agent_id, response
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [1, 2]))
    assert sorted(response.status_code for _, response in results) == [200, 409]
    winner = next(agent_id for agent_id, response in results if response.status_code == 200)
    loser = next(response for _, response in results if response.status_code == 409)
    assert loser.json()["detail"]["assignee_id"] == winner
    assert loser.json()["detail"]["assignee_name"]
    # A losing claimant cannot bypass the claim result and send another answer.
    for agent_id, _ in results:
        reply = client.post(f'/tickets/{seeded_ticket["id"]}/messages',
                            headers=credentials[agent_id],
                            json={"body": f"Reply from agent {agent_id}"})
        assert reply.status_code == (201 if agent_id == winner else 409)
    with psycopg.connect(url) as db:
        assert db.execute("SELECT assignee_id FROM tickets WHERE id = %s", (seeded_ticket["id"],)).fetchone()[0] == winner
        events = db.execute("SELECT actor, after_value FROM events WHERE event_type = 'claimed'").fetchall()
        assert len(events) == 1
        assert events[0] == (f"agent:{winner}", {"assignee_id": winner})
        assert db.execute("SELECT count(*) FROM public_messages").fetchone()[0] == 1


def test_claim_requires_agent_and_conflicts_on_second_claim(harness, seeded_ticket, agent_headers):
    client, _, _ = harness
    path = f'/tickets/{seeded_ticket["id"]}/claim'
    assert client.post(path).status_code == 401
    assert client.post(path, headers=agent_headers).status_code == 200
    assert client.post(path, headers=agent_headers).status_code == 200
    assert client.post('/tickets/999999/claim', headers=agent_headers).status_code == 404


def test_unclaimed_ticket_requires_claim_for_public_agent_reply(harness, seeded_ticket, agent_headers):
    client, url, _ = harness
    response = client.post(f'/tickets/{seeded_ticket["id"]}/messages', headers=agent_headers, json={"body": "Answer without claiming"})
    assert response.status_code == 409
    with psycopg.connect(url) as db:
        assert db.execute("SELECT count(*) FROM public_messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
