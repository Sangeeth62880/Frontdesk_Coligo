"""Deterministic six-case review seed for a fresh schema, using normal mutations.

Never clear/rewrite existing tickets or audit events. Run with an owner connection:
uv run --env-file .env python -m scripts.seed_review_demo --as-of 2026-11-16T10:00:00+05:30
Use an empty, migrated schema; reruns return the six IDs without modifying them.
"""
import argparse
import json
import os
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from frontdesk.business_time import ZONE


def seed_review(db,instant):
    instant=instant.astimezone(ZONE)
    db.execute('SELECT pg_advisory_xact_lock(7220261123)')
    existing=db.execute("SELECT id FROM tickets WHERE customer_email='review-seed@arvo.example' ORDER BY id").fetchall()
    if existing:
        if len(existing)!=6:raise ValueError('Incomplete review seed; use a new empty schema')
        return [r['id'] for r in existing]
    if db.execute('SELECT count(*) AS n FROM tickets').fetchone()['n']:
        raise ValueError('Review seed requires a fresh empty schema; existing immutable records are preserved')
    from scripts.seed_demo import seed_cases
    return seed_cases(db,instant,review=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--as-of',required=True,type=datetime.fromisoformat)
    args=parser.parse_args()
    if args.as_of.tzinfo is None:raise ValueError('--as-of requires a timezone offset')
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as db:
        ids=seed_review(db,args.as_of)
    print(json.dumps({'review_ticket_ids':ids,'as_of':args.as_of.isoformat()}))


if __name__=='__main__':main()
