from html.parser import HTMLParser
from datetime import datetime

import psycopg
import pytest


@pytest.mark.parametrize('priority', ['urgent', 'medium', 'small'])
@pytest.mark.parametrize('source', [None, 'customer', 'agent'])
def test_ticket_creation_source_paths(harness, agent_headers, priority, source):
    client, url, _ = harness
    body = {'subject': 'Source test', 'customer_email': 'customer@example.com', 'priority': priority}
    customer = client.post('/customer/tickets', json=body)
    assert customer.status_code == 201
    if source is not None:
        body['source'] = source
    response = client.post('/tickets', headers=agent_headers | {'X-Agent-Id': '2'}, json=body)
    assert response.status_code == 201
    ticket_id = response.json()['id']
    view = client.get(f'/tickets/{ticket_id}', headers=agent_headers).json()
    customer_view = client.get(f'/tickets/{customer.json()["id"]}', headers=agent_headers).json()
    required = source != 'agent'
    assert view['first_reply_required'] == required
    expected_due = customer_view['sla']['first_reply_due_at'] if required else None
    assert view['first_reply_due_at'] == view['sla']['first_reply_due_at'] == expected_due
    assert view['sla']['resolution_due_at'] == customer_view['sla']['resolution_due_at']
    assert view['start_at'] == customer_view['start_at']
    assert view['assignee_id'] is None and view['status'] == 'open'
    assert response.json()['customer_token']
    with psycopg.connect(url) as db:
        assert db.execute('SELECT first_reply_required, first_reply_due_at FROM tickets WHERE id=%s', (ticket_id,)).fetchone() == (required, view['first_reply_due_at'] and datetime.fromisoformat(view['first_reply_due_at']))
        events = db.execute('SELECT actor,event_type,after_value FROM events WHERE ticket_id=%s', (ticket_id,)).fetchall()
        assert len(events) == 1
        assert events[0][0:2] == ('agent:1', 'created')
        assert events[0][2]['source'] == (source or 'customer')
        assert db.execute("SELECT after_value->>'source' FROM events WHERE ticket_id=%s AND event_type='created'", (customer.json()['id'],)).fetchone()[0] == 'customer'


def test_invalid_ticket_source_does_not_create(harness, agent_headers):
    c, url, _ = harness
    for value in ['other', None, 1]:
        response = c.post('/tickets', headers=agent_headers, json={'subject':'Invalid', 'customer_email':'c@example.com', 'source':value})
        assert response.status_code == 422
    # Public intake keeps its original contract; clients cannot disable its SLA.
    response = c.post('/customer/tickets', json={'subject':'Invalid', 'customer_email':'c@example.com', 'source':'agent'})
    assert response.status_code == 422
    with psycopg.connect(url) as db:
        assert db.execute('SELECT count(*) FROM tickets').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 0


def test_create_form_source_options_and_priority_hints(harness):
    class Controls(HTMLParser):
        def __init__(self):
            super().__init__()
            self.select = None
            self.controls = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'select':
                self.select = attrs.get('name')
                self.controls[self.select] = []
            if tag == 'option' and self.select:
                self.controls[self.select].append([attrs, ''])
        def handle_data(self, data):
            if self.select and self.controls[self.select]:
                self.controls[self.select][-1][1] += data
        def handle_endtag(self, tag):
            if tag == 'select': self.select = None
    parser = Controls()
    parser.feed(harness[0].get('/').text)
    options = parser.controls['source']
    assert [(attrs['value'], text) for attrs, text in options] == [('customer', 'Customer request'), ('agent', 'Agent-initiated')]
    assert 'selected' in options[0][0] and 'selected' not in options[1][0]
    assert [text for _, text in parser.controls['priority']] == ['Medium · Reply in 4.5 working hours', 'Urgent · Customer cannot work', 'Small · Question or request']
