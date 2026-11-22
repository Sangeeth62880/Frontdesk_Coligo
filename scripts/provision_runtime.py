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
        database_row = db.execute('SELECT current_database()').fetchone()
        assert database_row is not None
        name = database_row[0]
        db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(name), sql.Identifier(role)))
        schema_row = db.execute('SELECT current_schema()').fetchone()
        assert schema_row is not None
        schema = schema_row[0]
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        for table in ['agents', 'holidays', 'sla_policies']:
            db.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
        for table in ['tickets', 'ticket_pauses', 'resolution_cycles', 'request_idempotency', 'agent_sessions', 'agent_login_attempts', 'customer_intake_limits']:
            db.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON {} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
        db.execute(sql.SQL('GRANT DELETE ON agent_login_attempts, customer_intake_limits TO {}').format(sql.Identifier(role)))
        for table in ['public_messages', 'internal_notes', 'events']:
            db.execute(sql.SQL('GRANT SELECT, INSERT ON {} TO {}').format(sql.Identifier(table), sql.Identifier(role)))
        db.execute(sql.SQL('REVOKE UPDATE, DELETE, TRUNCATE ON events FROM {}').format(sql.Identifier(role)))
        db.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
    values = conninfo_to_dict(admin_url)
    values.update(user=role, password=password)
    return make_conninfo(**{key: str(value) for key, value in values.items() if value is not None})


if __name__ == '__main__':
    provision(os.environ['DATABASE_URL'], os.environ['FRONTDESK_DB_PASSWORD'])
    print('Restricted application database role provisioned')


def verify_runtime(runtime_url):
    """Fail release startup if the actual request role can edit immutable events."""
    with psycopg.connect(runtime_url) as db:
        role = db.execute("SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit FROM pg_roles WHERE rolname=current_user").fetchone()
        assert role is not None
        permissions = db.execute("SELECT has_table_privilege(current_user,'events','SELECT'),has_table_privilege(current_user,'events','INSERT'),has_table_privilege(current_user,'events','UPDATE'),has_table_privilege(current_user,'events','DELETE'),has_table_privilege(current_user,'events','TRUNCATE')").fetchone()
        triggers = sorted(row[0] for row in db.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='events'::regclass AND NOT tgisinternal AND tgenabled IN ('O','A')"))
        owner = db.execute("SELECT relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_class WHERE oid='events'::regclass").fetchone()
        if any(role[1:]) or permissions != (True, True, False, False, False) or not owner or owner[0]:
            raise RuntimeError('Runtime role failed immutable-event privilege verification')
        if triggers != ['events_immutable', 'events_no_truncate', 'events_server_timestamp']:
            raise RuntimeError('Required event protection triggers are missing or disabled')
        return {'event': 'database_runtime_verified', 'role': role[0], 'elevated_privileges': False,
                'events_select': True, 'events_insert': True, 'events_update_delete_truncate': False,
                'event_triggers': triggers, 'owns_events': False}
