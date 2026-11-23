import json
import subprocess
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

import psycopg
import pytest

from tests.conftest import login_headers
from tests.test_mutations import create, event_types


def rendered_ui(client,headers,ticket_id):
    result=subprocess.run(['node','tests/ui_smoke.cjs'],input=json.dumps({
        'agents':client.get('/agents',headers=headers).json(),
        'tickets':client.get('/tickets?assignee=all',headers=headers).json(),
        'detail':client.get(f'/tickets/{ticket_id}',headers=headers).json(),
        'events':event_types(client,ticket_id,headers)}),text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


class Tags(HTMLParser):
    def __init__(self):super().__init__();self.tags=[];self.text=[]
    def handle_starttag(self,tag,attrs):self.tags.append(tag)
    def handle_data(self,data):self.text.append(data)


def test_raw_html_escaped_in_actual_agent_and_customer_renderers(harness,agent_headers):
    c,url,_=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    c.post(p+'/claim',headers=agent_headers)
    raw='  <script>alert("xss")</script><b>raw HTML & text</b>\n'
    assert c.post(p+'/messages',headers=agent_headers,json={'body':raw}).status_code==201
    c.post(p+'/notes',headers=agent_headers,json={'body':'NOTE_MARKER_7f3a'})
    with psycopg.connect(url) as db:assert db.execute("SELECT body FROM public_messages WHERE author_type='agent'").fetchone()[0]==raw
    html=rendered_ui(c,agent_headers,t['id'])['detail']
    parser=Tags();parser.feed(html)
    assert 'script' not in parser.tags and 'b' not in parser.tags
    assert raw in ''.join(parser.text)
    assert 'Team-only' in html and 'NOTE_MARKER_7f3a' in html
    assert 'Meera' in html and 'First reply sent' in html
    # Execute the shipped customer renderer too, with a mocked network response.
    public=c.get(f'/customer/tickets/{t["id"]}',headers={'X-Customer-Token':t['customer_token']}).json()
    script="""const fs=require('node:fs'),vm=require('node:vm');const data=JSON.parse(fs.readFileSync(0,'utf8'));const target={innerHTML:'',addEventListener(){}};const ctx=vm.createContext({document:{querySelector:()=>target},sessionStorage:{getItem:()=>JSON.stringify({id:'1',token:'test'})},location:{hash:''},fetch:async()=>({ok:true,json:async()=>data}),Intl,Date});vm.runInContext(fs.readFileSync('frontdesk/static/customer.js','utf8'),ctx);setImmediate(()=>process.stdout.write(target.innerHTML));"""
    customer_html=subprocess.run(['node','-e',script],input=json.dumps(public),text=True,capture_output=True,check=True).stdout
    parser=Tags();parser.feed(customer_html)
    assert 'script' not in parser.tags and 'b' not in parser.tags
    assert raw in ''.join(parser.text)
    assert 'NOTE_MARKER' not in customer_html and 'Team-only' not in customer_html

@pytest.mark.parametrize('body',['','   ','\n\t','x'*10001])
@pytest.mark.parametrize('endpoint',['notes','messages','customer-reply'])
def test_invalid_bodies_422(harness,agent_headers,body,endpoint):
    c,_,_=harness;t=create(c,agent_headers)
    headers={'X-Customer-Token':t['customer_token']} if endpoint=='customer-reply' else agent_headers
    r=c.post(f'/tickets/{t["id"]}/{endpoint}',headers=headers,json={'body':body})
    assert r.status_code==422
    assert len(event_types(c,t['id'],agent_headers))==1

@pytest.mark.parametrize('method',['PUT','PATCH','DELETE'])
@pytest.mark.parametrize('suffix',['/events','/events/1'])
def test_audit_api_immutable(harness,agent_headers,method,suffix):
    c,_,_=harness;t=create(c,agent_headers)
    assert c.request(method,f'/tickets/{t["id"]}'+suffix,headers=agent_headers,json={'actor':'forged'}).status_code in (404,405)


def test_unknown_ids_and_malformed_input(harness,agent_headers):
    c,_,_=harness
    for endpoint,body in [('',None),('/events',None),('/claim',{}),('/notes',{'body':'x'}),('/messages',{'body':'x'}),('/status',{'status':'resolved','version':0}),('/priority',{'priority':'urgent'}),('/reassign',{'assignee_id':1})]:
        r=c.get('/tickets/999999'+endpoint,headers=agent_headers) if body is None else c.post('/tickets/999999'+endpoint,headers=agent_headers,json=body)
        assert r.status_code==404
    for body in [None,[],1,{'status':'bogus'}, {'status':'resolved','version':-1}, {'status':'resolved','version':0,'created_at':'naive'}]:
        r=c.post('/tickets/1/status',headers=agent_headers,json=body)
        assert r.status_code==422
    assert c.get('/tickets/not-an-id',headers=agent_headers).status_code==422
    assert c.post('/tickets/1/messages',headers=agent_headers,content='{').status_code==422


def test_mutation_event_counts_and_inc0318_event_derived_reply(harness,agent_headers):
    c,url,now=harness;t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    def exactly(kind,action):
        before=event_types(c,t['id'],agent_headers)
        response=action();assert response.status_code<300,response.text
        after=event_types(c,t['id'],agent_headers)
        assert len([e for e in after if e['event_type']==kind])==len([e for e in before if e['event_type']==kind])+1
        return response
    assert event_types(c,t['id'],agent_headers)[0]['event_type']=='created'
    exactly('claimed',lambda:c.post(p+'/claim',headers=agent_headers))
    exactly('internal_note_added',lambda:c.post(p+'/notes',headers=agent_headers,json={'body':'NOTE_MARKER_7f3a'}))
    now[0]+=timedelta(minutes=3)
    first=now[0]
    exactly('public_reply',lambda:c.post(p+'/messages',headers=agent_headers,json={'body':'Public'}))
    view=c.get(p,headers=agent_headers).json()
    assert datetime.fromisoformat(view['first_reply_at'])==first and view['first_reply_actor']=='agent:1'
    # The display is reconstructed from events even if a materialized field is damaged.
    with psycopg.connect(url) as db:db.execute('UPDATE tickets SET first_replied_at=NULL WHERE id=%s',(t['id'],))
    assert c.get(p,headers=agent_headers).json()['first_reply_at']==view['first_reply_at']
    with psycopg.connect(url) as db:db.execute('UPDATE tickets SET first_replied_at=%s WHERE id=%s',(first,t['id']))
    exactly('priority_changed',lambda:c.post(p+'/priority',headers=agent_headers,json={'priority':'urgent'}))
    version=c.get(p,headers=agent_headers).json()['version']
    exactly('paused',lambda:c.post(p+'/status',headers=agent_headers,json={'status':'waiting_on_customer','body':'Question','version':version}))
    exactly('resumed',lambda:c.post(p+'/customer-reply',headers={'X-Customer-Token':t['customer_token']},json={'body':'Answer'}))
    exactly('reassigned',lambda:c.post(p+'/reassign',headers=agent_headers,json={'assignee_id':2}))
    version=c.get(p,headers=agent_headers).json()['version']
    exactly('status_changed',lambda:c.post(p+'/status',headers=login_headers(c,2),json={'status':'resolved','version':version}))
    exactly('reopened',lambda:c.post(p+'/reopen',headers={'X-Customer-Token':t['customer_token']}))
    events=event_types(c,t['id'],agent_headers)
    assert [e['id'] for e in events]==sorted(e['id'] for e in events)
    assert [datetime.fromisoformat(e['created_at']) for e in events]==sorted(datetime.fromisoformat(e['created_at']) for e in events)
    for e in events:
        assert e['actor'] in {'customer','agent:1','agent:2'} and 'before_value' in e and 'after_value' in e
        if e['actor']=='agent:2':
            assert e['event_type']=='status_changed' and e['after_value']['status']=='resolved'
        stamp=datetime.fromisoformat(e['created_at'])
        assert abs(datetime.now(UTC)-stamp)<timedelta(minutes=2)
        assert 'NOTE_MARKER' not in json.dumps(e)
