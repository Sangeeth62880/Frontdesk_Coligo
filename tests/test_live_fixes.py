from tests.conftest import login_headers


def test_owner_status_priority_and_unassigned_triage(harness, agent_headers):
    c, _, _ = harness
    other = login_headers(c, 2)
    t = c.post('/tickets', headers=agent_headers, json={'subject':'Permission regression','customer_email':'permissions@example.com'}).json()
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
