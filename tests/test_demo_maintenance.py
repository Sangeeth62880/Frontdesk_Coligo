"""One-shot demo maintenance tested only in disposable isolated schemas."""
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from frontdesk.auth import verify_password
from scripts.maintain_demo import maintain
from tests.conftest import TEST_PASSWORD


@pytest.fixture
def maintenance(api_db, monkeypatch):
    monkeypatch.setenv('FRONTDESK_SEED_DEMO','true')
    monkeypatch.setenv('FRONTDESK_DEMO_PASSWORD',TEST_PASSWORD)
    operations='ops_test_'+uuid4().hex
    with psycopg.connect(api_db,row_factory=dict_row) as db:
        identity=db.execute('SELECT current_schema() AS schema,current_database() AS database').fetchone()
    def run(db,action='reset-demo',nonce=None,confirmed=None):
        return maintain(db,action,nonce or str(uuid4()),confirmed or identity['database'],schema=identity['schema'],operations_schema=operations)
    yield api_db,run,identity,operations
    with psycopg.connect(api_db) as db:
        db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(operations)))


def test_reset_once_then_password_rotation_preserves_events_and_revokes_sessions(maintenance,monkeypatch):
    url,run,_identity,operations=maintenance
    nonce=str(uuid4())
    with psycopg.connect(url,row_factory=dict_row) as db:
        result=run(db,nonce=nonce)
        assert result=={'event':'demo_reset_verified','tickets':8,'internal_notes':2,'invalid_timelines':0,'synthetic_subjects':0}
        events=db.execute('SELECT * FROM events ORDER BY id').fetchall()
        tickets=db.execute('SELECT * FROM tickets ORDER BY id').fetchall()
        assert run(db,nonce=nonce)['event']=='demo_maintenance_already_completed'
        assert db.execute('SELECT * FROM events ORDER BY id').fetchall()==events
        assert db.execute('SELECT * FROM tickets ORDER BY id').fetchall()==tickets
        assert db.execute('SELECT count(*) AS n FROM schema_migrations').fetchone()['n']==11
        agent=db.execute("SELECT id FROM agents WHERE email='meera@arvo.example'").fetchone()['id']
        db.execute("INSERT INTO agent_sessions(token_hash,agent_id,created_at,expires_at) VALUES (repeat('a',64),%s,clock_timestamp(),clock_timestamp()+interval '1 hour')",(agent,))
        monkeypatch.setenv('FRONTDESK_DEMO_PASSWORD',TEST_PASSWORD+'rotated')
        assert run(db,'rotate-demo-password')['accounts']==3
        assert db.execute("SELECT revoked_at FROM agent_sessions WHERE token_hash=repeat('a',64)").fetchone()['revoked_at'] is not None
        for row in db.execute("SELECT password_hash FROM agents WHERE name IN ('Meera','Arun','Divya')"):
            assert verify_password(TEST_PASSWORD+'rotated',row['password_hash'])
            assert not verify_password(TEST_PASSWORD,row['password_hash'])
        assert db.execute('SELECT * FROM events ORDER BY id').fetchall()==events
        assert db.execute('SELECT * FROM tickets ORDER BY id').fetchall()==tickets
        assert db.execute(sql.SQL('SELECT count(*) AS n FROM {}.completed').format(sql.Identifier(operations))).fetchone()['n']==2


def test_maintenance_wrong_database_or_nonce_fails_before_mutation(maintenance):
    url,run,_identity,operations=maintenance
    with psycopg.connect(url,row_factory=dict_row) as db:
        original=db.execute('SELECT count(*) AS n FROM agents').fetchone()['n']
        with pytest.raises(ValueError,match='confirmation'):
            run(db,confirmed='a_different_database')
        with pytest.raises(ValueError):
            run(db,nonce='not-a-nonce')
        assert db.execute('SELECT count(*) AS n FROM agents').fetchone()['n']==original
        assert db.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(operations,)).fetchone() is None


def test_maintenance_reset_rolls_back_entire_schema_on_seed_failure(maintenance,monkeypatch):
    from scripts import maintain_demo
    url,run,_identity,operations=maintenance
    with psycopg.connect(url,row_factory=dict_row) as db:
        before=db.execute('SELECT * FROM agents ORDER BY id').fetchall()
        def failure(db):raise RuntimeError('seed failed')
        monkeypatch.setattr(maintain_demo,'seed',failure)
        with pytest.raises(RuntimeError,match='seed failed'),db.transaction():
            run(db)
        assert db.execute('SELECT * FROM agents ORDER BY id').fetchall()==before
        assert db.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(operations,)).fetchone() is None


def test_nonowner_cannot_run_demo_maintenance(maintenance):
    url,run,_identity,operations=maintenance
    role='maintenance_runtime_'+uuid4().hex
    with psycopg.connect(url,autocommit=True) as owner:
        owner.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(role)))
        try:
            with psycopg.connect(url,row_factory=dict_row) as db, db.transaction():
                db.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                with pytest.raises(ValueError,match='owner'):
                    run(db)
            assert owner.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(operations,)).fetchone() is None
        finally:
            owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
