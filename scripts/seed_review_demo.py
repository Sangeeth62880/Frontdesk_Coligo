"""Deterministic six-case review seed for a fresh schema, using normal mutations.

Never clear/rewrite existing tickets or audit events. Run with an owner connection:
uv run --env-file .env python -m scripts.seed_review_demo --as-of 2026-11-23T10:00:00+05:30
Use an empty, migrated schema; reruns return the six IDs without modifying them.
"""
import argparse
import json
import os
from datetime import datetime, time, timedelta

import psycopg
from psycopg.rows import dict_row

from frontdesk import service
from frontdesk.business_time import ZONE
from frontdesk.events import log_event


def seed_review(db,instant):
    instant=instant.astimezone(ZONE)
    db.execute('SELECT pg_advisory_xact_lock(7220261123)')
    existing=db.execute("SELECT id FROM tickets WHERE customer_email='review-seed@arvo.example' ORDER BY id").fetchall()
    if existing:
        if len(existing)!=6:raise ValueError('Incomplete review seed; use a new empty schema')
        return [r['id'] for r in existing]
    if db.execute('SELECT count(*) AS n FROM tickets').fetchone()['n']:
        raise ValueError('Review seed requires a fresh empty schema; existing immutable records are preserved')
    calendar,_=service.calendar_and_policy(db,'medium')
    def back(days):
        day=instant.date()
        while days:
            day-=timedelta(days=1)
            if calendar.working(day):days-=1
        return datetime.combine(day,time(10),ZONE)
    def create(label,priority,at,claim=True):
        t=service.create_ticket(db,'Review demo: '+label,'review-seed@arvo.example',priority,at,'system',source='customer')
        if claim:
            t=db.execute('UPDATE tickets SET assignee_id=1 WHERE id=%s RETURNING *',(t['id'],)).fetchone()
            log_event(db,t['id'],'agent:1','claimed',before={'assignee_id':None},after={'assignee_id':1})
        return t
    late=create('Late invoice export','medium',back(7))
    waiting=create('Waiting for workspace ID','medium',back(1))
    service.public_message(db,waiting,'Please supply your workspace ID.',back(1)+timedelta(minutes=5),'agent:1',1)
    waiting=service.locked_ticket(db,waiting['id'])
    service.change_status(db,waiting,'waiting_on_customer',back(1)+timedelta(minutes=5),'agent:1')
    friday=instant.date()
    while friday.weekday()!=4 or not calendar.working(friday) or datetime.combine(friday,time(18),ZONE)>instant:
        friday-=timedelta(days=1)
    evening=create('Friday evening question','small',datetime.combine(friday,time(18),ZONE),False)
    near=create('Near reopen window','medium',back(6))
    service.public_message(db,near,'The reporting filter has been corrected.',back(6)+timedelta(minutes=5),'agent:1',1)
    service.change_status(db,service.locked_ticket(db,near['id']),'resolved',back(4),'agent:1')
    urgent=create('Urgent service interruption','urgent',instant)
    unassigned=create('Unassigned customer question','small',instant,False)
    return [t['id'] for t in (late,waiting,evening,near,urgent,unassigned)]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--as-of',required=True,type=datetime.fromisoformat)
    args=parser.parse_args()
    if args.as_of.tzinfo is None:raise ValueError('--as-of requires a timezone offset')
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as db:
        ids=seed_review(db,args.as_of)
    print(json.dumps({'review_ticket_ids':ids,'as_of':args.as_of.isoformat()}))


if __name__=='__main__':main()
