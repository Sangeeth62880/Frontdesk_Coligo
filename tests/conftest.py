import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient

from frontdesk.api import create_app
from frontdesk.business_time import ZONE
from datetime import datetime


@pytest.fixture
def api_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for API integration tests")
    schema = "api_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        isolated = make_conninfo(url, options=f"-csearch_path={schema}")
        try:
            with psycopg.connect(isolated) as db:
                for migration in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
                    db.execute(migration.read_text())
            yield isolated
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def harness(api_db):
    now = [datetime(2026, 11, 23, 10, tzinfo=ZONE)]
    app = create_app(api_db, agent_token="test-agent-secret", sweep_token="test-sweep-secret", clock=lambda: now[0], sweep_interval=0)
    with TestClient(app) as client:
        yield client, api_db, now


@pytest.fixture
def seeded_ticket(api_db):
    with psycopg.connect(api_db, row_factory=dict_row) as db:
        ticket = db.execute("INSERT INTO tickets(subject, customer_email, priority, start_at) VALUES ('Printer offline', 'customer@example.com', 'medium', '2026-11-23 10:00+05:30') RETURNING *").fetchone()
        db.execute("INSERT INTO resolution_cycles(ticket_id, cycle_number, opened_at, start_at) VALUES (%s,1,%s,%s)", (ticket["id"], ticket["start_at"], ticket["start_at"]))
        return ticket


@pytest.fixture
def agent_headers():
    return {"Authorization": "Bearer test-agent-secret", "X-Agent-Id": "1"}
