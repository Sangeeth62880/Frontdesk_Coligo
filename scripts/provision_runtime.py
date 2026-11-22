"""Provision a restricted application role; credentials never enter output."""
import os

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def provision(admin_url, password, role='frontdesk_app'):
    if not password:
        raise ValueError('A non-empty runtime database password is required')
    with psycopg.connect(admin_url) as db:
        exists = db.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
        if exists and any(exists):
            raise ValueError('Existing runtime role must not have elevated privileges')
        # Managed PostgreSQL owners cannot ALTER the SUPERUSER attribute, even
        # to false. Validate privileged attributes above and preserve them on repeat boots.
        statement = 'ALTER ROLE {} WITH LOGIN NOINHERIT PASSWORD {}' if exists else 'CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}'
        db.execute(sql.SQL(statement).format(sql.Identifier(role), sql.Literal(password)))
        name = db.execute('SELECT current_database()').fetchone()[0]
        db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(name), sql.Identifier(role)))
        schema = db.execute('SELECT current_schema()').fetchone()[0]
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        for table in ['agents', 'holidays', 'sla_policies']:
            db.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
        for table in ['tickets', 'ticket_pauses', 'resolution_cycles', 'request_idempotency', 'agent_sessions', 'agent_login_attempts']:
            db.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON {} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
        db.execute(sql.SQL('GRANT DELETE ON agent_login_attempts TO {}').format(sql.Identifier(role)))
        for table in ['public_messages', 'internal_notes', 'events']:
            db.execute(sql.SQL('GRANT SELECT, INSERT ON {} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
        db.execute(sql.SQL('REVOKE UPDATE, DELETE, TRUNCATE ON events FROM {}').format(sql.Identifier(role)))
        db.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
    values = conninfo_to_dict(admin_url)
    values.update(user=role, password=password)
    return make_conninfo(**values)


if __name__ == '__main__':
    provision(os.environ['DATABASE_URL'], os.environ['FRONTDESK_DB_PASSWORD'])
    print('Restricted application database role provisioned')
