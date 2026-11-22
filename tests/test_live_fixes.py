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


def test_resolution_public_message_is_atomic_idempotent_and_first_reply(harness, agent_headers):
    c, _, _ = harness
    t = c.post('/tickets', headers=agent_headers, json={'subject':'Resolution message','customer_email':'resolved@example.com'}).json()
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
    assert [m['body'] for m in detail['messages']] == ['The issue is fixed.']
    public = c.get('/customer'+p, headers={'X-Customer-Token':t['customer_token']}).json()
    assert [m['body'] for m in public['messages']] == ['The issue is fixed.']
    assert 'Private investigation' not in str(public)
    after = c.get(p+'/events', headers=agent_headers).json()
    assert [e['event_type'] for e in after[len(before):]] == ['public_reply','status_changed']
    assert c.post(p+'/status', headers=headers, json=payload | {'body':'Different'}).status_code == 409
    assert c.get(p+'/events', headers=agent_headers).json() == after


def test_resolution_without_message_still_works(harness, agent_headers):
    c, _, _ = harness
    t = c.post('/tickets', headers=agent_headers, json={'subject':'No message','customer_email':'resolved@example.com'}).json()
    p = f'/tickets/{t["id"]}'
    assert c.post(p+'/claim', headers=agent_headers).status_code == 200
    version = c.get(p, headers=agent_headers).json()['version']
    assert c.post(p+'/status', headers=agent_headers, json={'status':'resolved','version':version}).status_code == 200
    assert c.get(p, headers=agent_headers).json()['messages'] == []
