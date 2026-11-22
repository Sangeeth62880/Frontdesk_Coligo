"""Hosted release lifecycle; creates labeled synthetic tickets, never edits demo data."""
import html
import json
import re
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import Page, Request, expect, sync_playwright

BASE = 'https://frontdesk-spfe.onrender.com'
OUT = Path('output/release')


def main():
    expect.set_options(timeout=30000)
    OUT.mkdir(parents=True, exist_ok=True)
    response = requests.get(BASE, timeout=120)
    match = re.search(r'Password: ([^<]*)</p>', response.text)
    if not match:
        raise RuntimeError('Enabled demo hint unavailable')
    password = html.unescape(match.group(1))
    stamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
    label = f'Hosted verification: release lifecycle {stamp}'
    payload = '<img src=x onerror="window.XSS_EXECUTED=true"> 👩🏽‍💻 e\u0301'
    result: dict[str, Any] = {'label': label, 'ticket_ids': [], 'checks': [], 'axe': {}}
    errors = []
    failed = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        a, b = browser.new_context(accept_downloads=True), browser.new_context()
        one, two = a.new_page(), b.new_page()
        inflight: dict[Page, set[Request]] = {one: set(), two: set()}
        progress = {'phase': 'setup'}
        def stage(name):
            progress['phase'] = name
            print('Browser stage: '+name, flush=True)
        def settle(page):
            deadline = time.monotonic()+30
            while True:
                page.wait_for_timeout(100)
                refreshing = page.evaluate("typeof refreshing !== 'undefined' && (refreshing || refreshAgain)")
                if not inflight.get(page) and not refreshing:
                    return
                assert time.monotonic() < deadline, 'Active requests did not settle'
        def navigate(page, url):
            # Explicit test navigation must not cancel the app's current refresh.
            settle(page)
            page.goto(url)
            settle(page)
        def track(page: Page):
            def started(request: Request):
                inflight[page].add(request)
            def finished(request: Request):
                inflight[page].discard(request)
            def request_failed(request: Request):
                inflight[page].discard(request)
                failed.append(f'{progress["phase"]}: {request.url.split("?")[0]}: {request.failure}')
            page.on('request', started)
            page.on('requestfinished', finished)
            page.on('requestfailed', request_failed)
        for page in (one, two):
            page.set_default_timeout(30000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            track(page)
        def axe(page, name):
            page.evaluate(Path('node_modules/axe-core/axe.min.js').read_text())
            violations = page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>({id:v.id,impact:v.impact}))")
            result['axe'][name] = violations
            assert not violations, (name, violations)
        def login(page, email):
            stage('sign in')
            navigate(page, BASE)
            page.locator('#login-email').fill(email)
            page.locator('#login-password').fill(password)
            page.get_by_role('button', name='Sign in', exact=True).click()
            expect(page.locator('#login-dialog')).not_to_be_visible()
            return page.evaluate("sessionStorage.getItem('frontdesk-key')")
        navigate(one, BASE)
        axe(one, 'login')
        token = login(one, 'meera@arvo.example')
        login(two, 'arun@arvo.example')
        headers = {'Authorization': 'Bearer '+token}
        stage('create and claim')
        one.get_by_role('button', name='New ticket', exact=True).click()
        one.locator('[name=subject]').fill(label+' '+payload)
        one.locator('[name=customer_email]').fill('release-verification@arvo.example')
        one.get_by_role('button', name='Create ticket', exact=True).click()
        expect(one.locator('#detail h1')).to_contain_text(label)
        ticket_id = int(one.url.rsplit('/', 1)[-1])
        result['ticket_ids'].append(ticket_id)
        path = f'/tickets/{ticket_id}'
        assert not one.evaluate('Boolean(window.XSS_EXECUTED)')
        for page in (one, two):
            navigate(page, BASE+'/#ticket/'+str(ticket_id))
            expect(page.get_by_role('button', name='Take this ticket')).to_be_visible()
        one.get_by_role('button', name='Take this ticket').click()
        expect(one.locator('#ticket-assignee')).to_have_text('Meera')
        two.get_by_role('button', name='Take this ticket').click()
        expect(two.locator('#toast')).to_contain_text('Meera')
        expect(two.locator('#ticket-assignee')).to_have_text('Meera')
        assert 'customer_token' not in one.request.get(BASE+path, headers=headers).json()
        listing = one.request.get(BASE+'/tickets?assignee=all', headers=headers).json()
        assert all('customer_token' not in row for row in listing)
        access = one.request.get(BASE+path+'/customer-access', headers=headers)
        assert access.status == 200
        capability = access.json()['customer_token']
        result['checks'].extend(['UI create', 'two-context claim conflict', 'list/detail capability absence', 'assignee-only customer access'])
        stage('agent conversation')
        one.get_by_role('button', name='Internal note', exact=True).click()
        expect(one.locator('#reply-form')).to_have_class('composer internal')
        one.locator('#reply-body').fill('RELEASE_PRIVATE_NOTE_'+stamp)
        one.get_by_role('button', name='Add note', exact=True).click()
        expect(one.locator('.message.internal')).to_contain_text('Team-only')
        one.get_by_role('button', name='Reply to customer', exact=True).click()
        one.locator('#reply-body').fill(payload)
        one.get_by_role('button', name='Send reply', exact=True).click()
        expect(one.locator('.message:not(.internal)')).to_have_count(1)
        assert not one.evaluate('Boolean(window.XSS_EXECUTED)')
        one.locator('#reply-body').fill('Please confirm the workspace ID.')
        one.locator('#ticket-status').select_option('waiting_on_customer')
        expect(one.locator('#ticket-status')).to_have_value('waiting_on_customer')
        one.locator('#ticket-priority').select_option('urgent')
        expect(one.locator('#ticket-priority')).to_have_value('urgent')
        one.locator('#activity').evaluate('(e)=>e.open=true')
        expect(one.locator('#activity')).to_contain_text('medium → urgent')
        axe(one, 'ticket')
        result['checks'].extend(['public/internal visuals', 'inert subject/body XSS', 'waiting public question', 'priority timeline snapshot'])
        customer = a.new_page()
        stage('customer conversation')
        customer.on('pageerror', lambda error: errors.append(str(error)))
        navigate(customer, BASE+f'/customer#{ticket_id}:{capability}')
        expect(customer.locator('h2')).to_contain_text(label)
        expect(customer.locator('body')).not_to_contain_text('RELEASE_PRIVATE_NOTE_')
        assert customer.url == BASE+'/customer'
        assert not customer.evaluate('Boolean(window.XSS_EXECUTED)')
        axe(customer, 'customer')
        customer.locator('#customer-body').fill('Workspace 42')
        customer.get_by_role('button', name='Send reply', exact=True).click()
        expect(customer.locator('#customer-notice')).to_have_text('Your reply was sent.')
        with customer.expect_download() as download:
            customer.get_by_role('button', name='Download ticket CSV').click()
        csv = Path(download.value.path()).read_text()
        assert label in csv and 'RELEASE_PRIVATE_NOTE_' not in csv
        download.value.save_as(str(OUT/'hosted-customer.csv'))
        one.get_by_label('Workspace menu').click()
        one.locator('#refresh').click()
        expect(one.locator('#ticket-status')).to_have_value('open')
        one.get_by_label('Ticket actions').click()
        one.once('dialog', lambda dialog: dialog.accept('Simulated release verification reply'))
        one.locator('#simulate').click()
        expect(one.locator('.thread')).to_contain_text('Simulated release verification reply')
        one.locator('#ticket-status').select_option('resolved')
        expect(one.get_by_label('Message to customer',exact=True)).to_be_visible()
        one.get_by_label('Message to customer',exact=True).fill('The workspace issue is resolved.')
        one.get_by_role('button',name='Resolve ticket',exact=True).click()
        expect(one.get_by_role('button', name='Reopen ticket')).to_be_visible()
        one.get_by_role('button', name='Reopen ticket').click()
        expect(one.locator('.detail-customer')).to_contain_text('Cycle 2')
        result['checks'].extend(['customer note privacy', 'customer answer resumes', 'native CSV download', 'simulated answer', 'resolve/reopen'])
        navigate(one, BASE+'/#tickets')
        stage('list and keyboard')
        one.locator('[data-queue=all]').click()
        one.locator('#search').fill(label)
        expect(one.locator('#ticket-list .ticket-row')).to_have_count(1)
        one.locator('#status-filter').select_option('waiting_on_customer')
        expect(one.locator('#ticket-list .ticket-row')).to_have_count(0)
        one.locator('#status-filter').select_option('all')
        expect(one.locator('#ticket-list .ticket-row')).to_have_count(1)
        axe(one, 'list')
        for width in (390, 768, 1280):
            one.set_viewport_size({'width': width, 'height': 900})
            assert one.evaluate('document.documentElement.scrollWidth<=innerWidth')
            one.screenshot(path=str(OUT/f'hosted-lifecycle-{width}.png'), full_page=True)
        one.locator('body').click(position={'x': 10, 'y': 200})
        one.keyboard.press('j'); one.keyboard.press('k'); one.keyboard.press('Enter')
        expect(one.locator('#detail h1')).to_contain_text(label)
        one.get_by_role('button', name='New ticket', exact=True).click()
        one.keyboard.press('Tab')
        assert one.evaluate("document.querySelector('#create-dialog').contains(document.activeElement)")
        one.keyboard.press('Escape')
        expect(one.locator('#create-dialog')).not_to_be_visible()
        expect(one.get_by_role('button', name='New ticket', exact=True)).to_be_focused()
        stage('logout')
        settle(one)
        one.get_by_label('Workspace menu').click(); one.locator('#signout').click()
        expect(one.locator('#login-dialog')).to_be_visible()
        settle(one)
        stage('back')
        one.go_back()
        settle(one)
        expect(one.locator('#login-dialog')).to_be_visible()
        assert one.evaluate("sessionStorage.getItem('frontdesk-key')") is None
        result['checks'].extend(['search/filter', 'responsive screenshots', 'j/k/Enter', 'dialog Tab/Esc/focus return', 'logout/back'])
        # Revoke the browser's current session externally, then verify its 401 path.
        fresh = login(one, 'meera@arvo.example')
        stage('revoke and refresh')
        settle(one)
        assert one.request.post(BASE+'/auth/logout', headers={'Authorization': 'Bearer '+fresh}).status == 200
        one.get_by_label('Workspace menu').click(); one.locator('#refresh').click()
        expect(one.locator('#login-dialog')).to_be_visible()
        result['checks'].append('revoked-session 401 redirects')
        result['js_errors'] = errors
        result['failed_requests'] = failed
        print(json.dumps({'js_errors': errors, 'failed_requests': failed}), flush=True)
        assert not errors and not failed, (errors, failed)
        result['unverified'] = ['12-hour natural expiry not waited; revoked-session 401 tested instead', 'lockout not induced on live demo agents', 'historical late-first ordering remains local deterministic coverage']
        a.close(); b.close(); browser.close()
    (OUT/'hosted-browser.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — browser snapshots can contain credentials.
        print(f'Hosted browser verification failed: {type(exc).__name__}', file=sys.stderr)
        for frame in traceback.extract_tb(exc.__traceback__):
            if frame.filename == __file__:
                print(f'{frame.name}: line {frame.lineno}', file=sys.stderr)
        sys.exit(1)
