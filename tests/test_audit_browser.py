"""Actual Chromium workflows against a migrated isolated local stack."""
import json
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import expect

from frontdesk.api import create_app
from frontdesk.business_time import ZONE
from tests.conftest import TEST_PASSWORD


@pytest.fixture
def browser_stack(api_db):
    clock=[datetime(2026,11,23,10,tzinfo=ZONE)]
    auth_clock=[clock[0]]
    app=create_app(api_db,sweep_interval=0,clock=lambda:clock[0],auth_clock=lambda:auth_clock[0])
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    base=f'http://127.0.0.1:{sock.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    stop=time.monotonic()+10
    while not server.started:
        assert thread.is_alive() and time.monotonic()<stop,'Test HTTP server did not start'
        time.sleep(.01)
    try:yield base,clock,auth_clock
    finally:
        server.should_exit=True
        thread.join(timeout=15)
        sock.close()
        assert not thread.is_alive()


def signin(page,base,email='meera@arvo.example'):
    page.goto(base)
    page.locator('#login-email').fill(email)
    page.locator('#login-password').fill(TEST_PASSWORD)
    page.get_by_role('button',name='Sign in',exact=True).click()
    expect(page.locator('#login-dialog')).not_to_be_visible()
    return page.evaluate("sessionStorage.getItem('frontdesk-key')")


def axe(page,label):
    source=Path('node_modules/axe-core/axe.min.js')
    assert source.exists(),'Run npm ci before the browser audit'
    page.evaluate(source.read_text())
    results=page.evaluate("async () => { const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}); return r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)})); }")
    out=Path('output/audit');out.mkdir(parents=True,exist_ok=True)
    (out/f'axe-{label}.json').write_text(json.dumps(results,indent=2))
    assert results==[],results


def test_browser_lifecycle_privacy_xss_csv_keyboard_and_responsive(browser,browser_stack):
    base,clock,_=browser_stack
    context=browser.new_context(accept_downloads=True)
    page=context.new_page()
    js_errors=[]; failed=[]; console_errors=[]
    page.on('pageerror',lambda error:js_errors.append(str(error)))
    page.on('console',lambda message:console_errors.append(message.text) if message.type=='error' else None)
    page.on('requestfailed',lambda request:failed.append(request.url.split('?')[0]))
    page.goto(base)
    expect(page.locator('#login-dialog')).to_be_visible()
    axe(page,'login')
    token=signin(page,base)
    headers={'Authorization':'Bearer '+token}
    payload='<img src=x onerror="window.XSS_EXECUTED=true"> \u202e 👩🏽‍💻 e\u0301'
    def create(subject,priority='medium'):
        r=page.request.post(base+'/tickets',headers=headers,data={'subject':subject,'customer_email':'browser@example.com','priority':priority})
        assert r.status==201
        return r.json()
    late=create('Browser: late','urgent')
    ticket=create('Browser: '+payload)
    clock[0]+=timedelta(days=1)
    fresh=create('Browser: fresh','small')
    fresh_path=base+f'/tickets/{fresh["id"]}'
    assert page.request.post(fresh_path+'/claim',headers=headers).status==200
    fresh_version=page.request.get(fresh_path,headers=headers).json()['version']
    assert page.request.post(fresh_path+'/status',headers=headers,data={'status':'waiting_on_customer','body':'Please confirm details.','version':fresh_version}).status==200
    page.locator('[data-queue=all]').click()
    page.locator('#status-filter').select_option('all')
    page.get_by_label('Workspace menu').click()
    page.locator('#refresh').click()
    page.get_by_label('Workspace menu').click()
    expect(page.locator('#ticket-list tr').first).to_have_attribute('data-ticket',str(late['id']))
    axe(page,'list')
    screens=Path('output/screens');screens.mkdir(parents=True,exist_ok=True)
    for width in (390,768,1280):
        page.set_viewport_size({'width':width,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        assert page.locator('.table-scroll').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),width
        expect(page.locator('.row-status .waiting')).to_have_text('Waiting')
        expect(page.locator('.row-status .waiting')).to_have_attribute('title','Waiting on customer')
        late_box=page.locator('.late-label').first.bounding_box()
        assert late_box and 0<=late_box['x'] and late_box['x']+late_box['width']<=width
        page.screenshot(path=str(screens/f'list-{width}.png'),full_page=True)
    page.set_viewport_size({'width':1280,'height':900})
    page.locator('#search').fill('fresh')
    expect(page.locator('#ticket-list tr')).to_have_count(1)
    page.locator('#search').fill('')
    page.locator('body').click(position={'x':10,'y':200})
    page.keyboard.press('j');page.keyboard.press('k');page.keyboard.press('Enter')
    expect(page.locator('#detail')).to_be_visible()
    page.goto(base+f'/#ticket/{ticket["id"]}')
    expect(page.locator('#detail h1')).to_contain_text(payload)
    assert not page.evaluate('Boolean(window.XSS_EXECUTED)')
    page.get_by_role('button',name='Take this ticket').click()
    expect(page.locator('#ticket-assignee')).to_have_text('Meera')
    page.get_by_role('button',name='Internal note',exact=False).click()
    expect(page.locator('#reply-form')).to_have_class('composer internal')
    page.locator('#reply-body').fill('PRIVATE_BROWSER_NOTE')
    page.get_by_role('button',name='Add note',exact=True).click()
    expect(page.locator('.message.internal')).to_contain_text('Team-only')
    page.get_by_role('button',name='Reply to customer',exact=True).click()
    page.locator('#reply-body').fill(payload)
    page.get_by_role('button',name='Send reply',exact=True).click()
    expect(page.locator('.message:not(.internal)')).to_have_count(1)
    assert not page.evaluate('Boolean(window.XSS_EXECUTED)')
    page.once('dialog',lambda dialog:dialog.dismiss())
    page.locator('#ticket-status').select_option('waiting_on_customer')
    expect(page.locator('#ticket-status')).to_have_value('open')
    page.locator('#reply-body').fill('Can you supply the workspace ID?')
    page.locator('#ticket-status').select_option('waiting_on_customer')
    expect(page.locator('#ticket-status')).to_have_value('waiting_on_customer')
    page.locator('#ticket-priority').select_option('urgent')
    expect(page.locator('#ticket-priority')).to_have_value('urgent')
    page.locator('#activity').evaluate('(e)=>e.open=true')
    expect(page.locator('#activity')).to_contain_text('medium → urgent')
    axe(page,'ticket')
    for width in (390,768,1280):
        page.set_viewport_size({'width':width,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        page.screenshot(path=str(screens/f'ticket-{width}.png'),full_page=True)
    page.set_viewport_size({'width':1280,'height':900})
    customer=context.new_page()
    customer.on('pageerror',lambda error:js_errors.append(str(error)))
    customer.goto(base+f'/customer#{ticket["id"]}:{ticket["customer_token"]}')
    expect(customer.locator('h2')).to_contain_text(payload)
    expect(customer.locator('body')).not_to_contain_text('PRIVATE_BROWSER_NOTE')
    assert customer.url==base+'/customer'
    assert not customer.evaluate('Boolean(window.XSS_EXECUTED)')
    axe(customer,'customer')
    customer.locator('#customer-body').fill('Workspace 42')
    customer.get_by_role('button',name='Send reply').click()
    expect(customer.locator('#customer-notice')).to_have_text('Your reply was sent.')
    with customer.expect_download() as download:
        customer.get_by_role('button',name='Download ticket CSV').click()
    content=Path(download.value.path()).read_text()
    assert payload in content.replace('""','"') and 'PRIVATE_BROWSER_NOTE' not in content
    download.value.save_as(str(Path('output/audit/customer.csv')))
    page.get_by_label('Workspace menu').click()
    page.locator('#refresh').click()
    expect(page.locator('#ticket-status')).to_have_value('open')
    page.get_by_label('Ticket actions').click()
    page.once('dialog',lambda dialog:dialog.accept('Simulated customer answer'))
    page.locator('#simulate').click()
    expect(page.locator('.thread')).to_contain_text('Simulated customer answer')
    page.locator('#ticket-status').select_option('resolved')
    expect(page.get_by_label('Message to customer',exact=True)).to_be_visible()
    page.get_by_label('Message to customer',exact=True).fill('The workspace issue is resolved.')
    page.get_by_role('button',name='Resolve ticket',exact=True).click()
    expect(page.get_by_role('button',name='Reopen ticket')).to_be_visible()
    page.get_by_role('button',name='Reopen ticket').click()
    expect(page.locator('.detail-customer')).to_contain_text('Cycle 2')
    page.get_by_role('button',name='New ticket',exact=True).click()
    expect(page.locator('#create-dialog')).to_be_visible()
    page.keyboard.press('Tab')
    assert page.evaluate("document.querySelector('#create-dialog').contains(document.activeElement)")
    page.keyboard.press('Escape')
    expect(page.locator('#create-dialog')).not_to_be_visible()
    expect(page.get_by_role('button',name='New ticket',exact=True)).to_be_focused()
    page.get_by_label('Workspace menu').click()
    page.locator('#signout').click()
    expect(page.locator('#login-dialog')).to_be_visible()
    page.go_back()
    expect(page.locator('#login-dialog')).to_be_visible()
    assert page.evaluate("sessionStorage.getItem('frontdesk-key')") is None
    Path('output/audit/browser-errors.json').write_text(json.dumps({'unexpected_js_errors':js_errors,'failed_network_requests':failed,'console_errors':console_errors},indent=2))
    assert not js_errors and not failed and not console_errors,(js_errors,failed,console_errors)
    context.close()


def test_browser_wrong_password_lockout_and_expired_401(browser,browser_stack):
    base,_,auth_clock=browser_stack
    context=browser.new_context()
    page=context.new_page()
    page.goto(base)
    page.locator('#login-email').fill('meera@arvo.example')
    page.locator('#login-password').fill('wrong')
    for _ in range(5):
        page.locator('#login-password').fill('wrong')
        with page.expect_response('**/auth/login') as response:
            page.get_by_role('button',name='Sign in',exact=True).click()
        assert response.value.status==401
        expect(page.locator('#login-error')).to_have_text('Unable to sign in. Check your email and password.')
        # The response precedes the submit handler's finally block. Do not let
        # that block clear the next attempt's freshly filled password.
        expect(page.get_by_role('button',name='Sign in',exact=True)).to_be_enabled()
        expect(page.locator('#login-password')).to_have_value('')
    page.locator('#login-password').fill(TEST_PASSWORD)
    page.get_by_role('button',name='Sign in',exact=True).click()
    expect(page.locator('#login-error')).to_contain_text('Too many')
    expect(page.get_by_role('button',name='Sign in',exact=True)).to_be_enabled()
    expect(page.locator('#login-password')).to_have_value('')
    auth_clock[0]+=timedelta(minutes=10)
    page.locator('#login-password').fill(TEST_PASSWORD)
    page.get_by_role('button',name='Sign in',exact=True).click()
    expect(page.locator('#login-dialog')).not_to_be_visible()
    auth_clock[0]+=timedelta(hours=12)
    page.get_by_label('Workspace menu').click()
    page.locator('#refresh').click()
    expect(page.locator('#login-dialog')).to_be_visible()
    assert page.evaluate("sessionStorage.getItem('frontdesk-key')") is None
    context.close()


def test_two_browser_context_claim_conflict(browser,browser_stack):
    base,_,_=browser_stack
    a,b=browser.new_context(),browser.new_context()
    one,two=a.new_page(),b.new_page()
    token=signin(one,base)
    signin(two,base,'arun@arvo.example')
    t=one.request.post(base+'/tickets',headers={'Authorization':'Bearer '+token},data={'subject':'Browser: competing claim','customer_email':'race@example.com'}).json()
    for page in (one,two):
        page.goto(base+f'/#ticket/{t["id"]}')
        expect(page.get_by_role('button',name='Take this ticket')).to_be_visible()
    one.get_by_role('button',name='Take this ticket').click()
    expect(one.locator('#ticket-assignee')).to_have_text('Meera')
    two.get_by_role('button',name='Take this ticket').click()
    expect(two.locator('#toast')).to_contain_text('Meera')
    expect(two.locator('#ticket-assignee')).to_have_text('Meera')
    expect(two.locator('a',has_text='Customer view')).to_have_count(0)
    expect(two.locator('#ticket-status')).to_be_disabled()
    expect(two.locator('#ticket-priority')).to_be_disabled()
    expect(two.locator('#ticket-status')).to_have_attribute('title', 'Assigned to Meera. Only Meera can resolve or wait.')
    expect(two.locator('#ticket-priority')).to_have_attribute('title', 'Assigned to Meera. Only Meera can change priority.')
    expect(one.locator('#ticket-status')).to_be_enabled()
    expect(one.locator('#ticket-priority')).to_be_enabled()
    a.close();b.close()
