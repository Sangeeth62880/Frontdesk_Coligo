"""Owner-only, idempotent demo seed with coherent historical audit timestamps."""
import os
from datetime import datetime, time, timedelta

import psycopg
from psycopg.rows import dict_row

from frontdesk import service
from frontdesk.auth import hash_password
from frontdesk.business_time import ZONE
from frontdesk.events import log_event


def seed_cases(db, instant, *, review=False):
    """Append a complete seed to an empty schema; never rewrite ticket history."""
    instant = instant.astimezone(ZONE)
    wall = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
    if instant > wall:
        raise ValueError('Seed time cannot be in the future')
    calendar, _ = service.calendar_and_policy(db, 'medium')
    db.execute("SELECT set_config('frontdesk.seeding','on',true)")
    def back(days):
        day = instant.date()
        while days:
            day -= timedelta(days=1)
            if calendar.working(day):
                days -= 1
        return datetime.combine(day, time(10), ZONE)
    def working_ago(minutes):
        cursor = instant
        while True:
            day = cursor.date()
            if calendar.working(day):
                end = min(cursor, calendar.boundary(day, calendar.closes))
                available = max(0, (end-calendar.boundary(day, calendar.opens)).total_seconds()/60)
                if minutes <= available:
                    return end-timedelta(minutes=minutes)
                minutes -= available
            cursor = calendar.boundary(day-timedelta(days=1), calendar.closes)
    def create(subject, description, label, priority, moment, owner):
        email = 'review-seed@arvo.example' if review else f'demo-{label}@arvo.example'
        ticket = service.create_ticket(db, subject, email, priority, moment, 'system', source='customer', body=description)
        if owner:
            ticket = db.execute('UPDATE tickets SET assignee_id=%s WHERE id=%s RETURNING *', (owner,ticket['id'])).fetchone()
            log_event(db,ticket['id'],f'agent:{owner}','claimed',before={'assignee_id':None},after={'assignee_id':owner},at=moment)
        return ticket
    def answer(ticket, text, moment):
        owner = ticket['assignee_id']
        service.public_message(db,ticket,text,moment,f'agent:{owner}',owner)
        return service.locked_ticket(db,ticket['id'])
    late_at = back(7)
    late = create('Invoice export stops partway through', 'Our finance team cannot download the monthly invoice export. The download stops before the file is complete.', 'late','medium',late_at,1)
    late = answer(late,'We reproduced the export failure and are investigating the worker logs.',late_at+timedelta(minutes=20))
    service.add_note(db,late['id'],'Coordinate the export retry with the billing team.',1,now=late_at+timedelta(minutes=25))
    waiting_at = back(1)
    waiting = create('Cannot sign in to the team workspace', 'Signing in returns an error after entering the workspace name. Other pages load normally.', 'waiting','medium',waiting_at,2)
    waiting = answer(waiting,'Please send your workspace ID and the exact error message.',waiting_at+timedelta(minutes=10))
    service.change_status(db,waiting,'waiting_on_customer',waiting_at+timedelta(minutes=10),'agent:2')
    service.add_note(db,waiting['id'],'Check the workspace mapping once the customer replies.',2,now=waiting_at+timedelta(minutes=20))
    friday = instant.date()
    while friday.weekday()!=4 or not calendar.working(friday) or datetime.combine(friday,time(18,45),ZONE)>instant:
        friday -= timedelta(days=1)
    evening = create('Add a second billing contact', 'We would like invoices sent to a second contact as well as the account owner.', 'friday','small',datetime.combine(friday,time(18,45),ZONE),None if review else 3)
    resolved_at = working_ago(2640)
    near_at = calendar.start(resolved_at-timedelta(days=3))
    near = create('Monthly dashboard totals differ from the report', 'The revenue total on our dashboard differs from the exported monthly report for the same period.', 'reopen','medium',near_at,1)
    near = answer(near,'We corrected the reporting filter. Please compare the totals again.',near_at+timedelta(minutes=20))
    service.change_status(db,near,'resolved',resolved_at,'agent:1')
    urgent = create('Checkout is unavailable for our customers', 'Customers cannot complete checkout and receive a service error when submitting payment.', 'urgent','urgent',instant-timedelta(minutes=30),2)
    unassigned = create('How can we update the company address', 'Please explain how to update the company address shown on future invoices.', 'unassigned','small',instant-timedelta(minutes=5),None)
    tickets = [late,waiting,evening,near,urgent,unassigned]
    if not review:
        done_at = back(1)
        done = create('Notification emails were sent twice', 'Several team members received duplicate notifications for the same update.', 'resolved','medium',done_at,3)
        done = answer(done,'The notification rule has been corrected and duplicate delivery has stopped.',done_at+timedelta(minutes=15))
        service.change_status(db,done,'resolved',done_at+timedelta(minutes=60),'agent:3')
        closed_at = back(8)
        closed = create('Need more details about a missing attachment', 'An attachment appears to be missing from an older support conversation.', 'closed','small',closed_at,2)
        closed = answer(closed,'Please share the conversation date and the attachment filename.',closed_at+timedelta(minutes=15))
        service.change_status(db,closed,'waiting_on_customer',closed_at+timedelta(minutes=15),'agent:2')
        threshold = calendar.add(closed_at+timedelta(minutes=15),2700)
        assert threshold <= instant
        service.auto_close(db,threshold)
        tickets.extend([done,closed])
    db.execute("SELECT set_config('frontdesk.seeding','off',true)")
    return [ticket['id'] for ticket in tickets]


def seed(db):
    db.execute('SELECT pg_advisory_xact_lock(7220261122)')
    if os.environ.get('FRONTDESK_SEED_DEMO','false').lower()=='true':
        password = os.environ.get('FRONTDESK_DEMO_PASSWORD')
        if not password:
            raise ValueError('FRONTDESK_DEMO_PASSWORD is required in demo mode')
        for email in ['meera@arvo.example','arun@arvo.example','divya@arvo.example']:
            db.execute('UPDATE agents SET password_hash=%s WHERE email=%s AND password_hash IS NULL',(hash_password(password),email))
    existing = db.execute("SELECT id FROM tickets WHERE customer_email LIKE 'demo-%@arvo.example' ORDER BY id").fetchall()
    if existing:
        return [row['id'] for row in existing]
    instant = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
    return seed_cases(db,instant)


if __name__=='__main__':
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as db:
        ids=seed(db)
    print(f'Demo ready: {len(ids)} representative tickets')
