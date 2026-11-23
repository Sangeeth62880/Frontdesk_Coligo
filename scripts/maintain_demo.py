"""Explicit owner-only, nonce-guarded demo maintenance; never a public route."""
import json
import logging
import os
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from frontdesk.auth import hash_password
from scripts.migrate import apply
from scripts.seed_demo import seed


def maintain(db, action, nonce, confirmed_database, *, schema='public', operations_schema='frontdesk_operations'):
    if action not in ('reset-demo', 'rotate-demo-password'):
        raise ValueError('Unknown demo maintenance action')
    if str(UUID(nonce)) != nonce or schema == operations_schema:
        raise ValueError('Invalid maintenance nonce or schema')
    identity = db.execute('SELECT current_database() AS database, current_user AS owner').fetchone()
    if not confirmed_database or identity['database'] != confirmed_database:
        raise ValueError('Maintenance database confirmation does not match')
    db.execute('SELECT pg_advisory_xact_lock(7220261121)')
    owner = db.execute('SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()
    database_owner = db.execute('SELECT pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname=current_database()').fetchone()
    if not owner or (owner['owner'] != identity['owner'] and database_owner['owner'] != identity['owner']):
        raise ValueError('Demo maintenance requires the schema or database owner')
    db.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(operations_schema)))
    db.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(operations_schema)))
    ledger = sql.Identifier(operations_schema, 'completed')
    db.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {} (nonce uuid PRIMARY KEY, action text NOT NULL, completed_at timestamptz NOT NULL DEFAULT clock_timestamp())').format(ledger))
    previous = db.execute(sql.SQL('SELECT action FROM {} WHERE nonce=%s').format(ledger), (nonce,)).fetchone()
    if previous:
        if previous['action'] != action:
            raise ValueError('Maintenance nonce already used for another action')
        return {'event': 'demo_maintenance_already_completed', 'action': action}
    if os.environ.get('FRONTDESK_SEED_DEMO', 'false').lower() != 'true' or not os.environ.get('FRONTDESK_DEMO_PASSWORD'):
        raise ValueError('Explicit demo mode and password are required for maintenance')
    if action == 'reset-demo':
        db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        db.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        apply(db)
        seed(db)
        summary = verify_demo(db)
    else:
        db.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        for name in ('meera', 'arun', 'divya'):
            row = db.execute('UPDATE agents SET password_hash=%s WHERE email=%s RETURNING id', (hash_password(os.environ['FRONTDESK_DEMO_PASSWORD']),name+'@arvo.example')).fetchone()
            if not row:
                raise ValueError('Missing demo account')
            db.execute('UPDATE agent_sessions SET revoked_at=clock_timestamp() WHERE agent_id=%s AND revoked_at IS NULL', (row['id'],))
        summary = {'event': 'demo_password_rotated', 'accounts': 3}
    db.execute(sql.SQL('INSERT INTO {} (nonce,action) VALUES (%s,%s)').format(ledger), (nonce,action))
    return summary


def verify_demo(db):
    counts = db.execute("SELECT count(*) AS tickets, count(*) FILTER (WHERE subject ILIKE '%%verification%%' OR subject LIKE '%%<%%') AS synthetic_subjects FROM tickets").fetchone()
    notes = db.execute('SELECT count(*) AS notes FROM internal_notes').fetchone()['notes']
    invalid = db.execute('''SELECT count(*) AS invalid FROM tickets t WHERE
        EXISTS (SELECT 1 FROM events e WHERE e.ticket_id=t.id AND (e.created_at<t.created_at OR e.created_at>clock_timestamp()))
        OR EXISTS (SELECT 1 FROM public_messages m WHERE m.ticket_id=t.id AND (m.created_at<t.created_at OR m.created_at>clock_timestamp()))
        OR t.first_replied_at IS DISTINCT FROM (SELECT min(m.created_at) FROM public_messages m WHERE m.ticket_id=t.id AND m.author_type='agent')''').fetchone()['invalid']
    if counts['tickets'] != 8 or counts['synthetic_subjects'] or notes != 2 or invalid:
        raise ValueError('Clean demo verification failed')
    return {'event':'demo_reset_verified', 'tickets':8, 'internal_notes':2, 'invalid_timelines':0, 'synthetic_subjects':0}


def from_environment():
    action = os.environ.get('FRONTDESK_ADMIN_ACTION')
    if not action:
        return
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as db:
        result = maintain(db, action, os.environ.get('FRONTDESK_ADMIN_NONCE', ''), os.environ.get('FRONTDESK_ADMIN_CONFIRM_DATABASE', ''))
    logging.getLogger('frontdesk.startup').info(json.dumps(result))
