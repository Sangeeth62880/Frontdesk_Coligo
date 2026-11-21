"""Idempotent synthetic demo cases. All notes and events use normal services."""
import os
from datetime import datetime, time, timedelta

import psycopg
from psycopg.rows import dict_row

from frontdesk import service
from frontdesk.business_time import ZONE
from frontdesk.events import log_event


def seed(db):
    db.execute("SELECT pg_advisory_xact_lock(7220261122)")
    existing = db.execute("SELECT id FROM tickets WHERE customer_email LIKE 'demo-%@arvo.example' ORDER BY id").fetchall()
    if existing:
        return [row["id"] for row in existing]
    now = db.execute("SELECT clock_timestamp() AS now").fetchone()["now"].astimezone(ZONE)
    calendar, _ = service.calendar_and_policy(db, "medium")
    def working_days_back(count):
        day = now.date()
        for _ in range(count):
            day -= timedelta(days=1)
            while not calendar.working(day):
                day -= timedelta(days=1)
        return day
    def at(day, hour=10):
        return datetime.combine(day, time(hour), ZONE)
    def create(subject, name, priority, moment, assigned=True):
        ticket = service.create_ticket(db, subject, f"demo-{name}@arvo.example", priority, moment, "system")
        if assigned:
            ticket = db.execute("UPDATE tickets SET assignee_id=1 WHERE id=%s AND assignee_id IS NULL RETURNING *", (ticket["id"],)).fetchone()
            log_event(db, ticket["id"], "agent:1", "claimed", before={"assignee_id": None}, after={"assignee_id": 1})
        return ticket
    old = at(working_days_back(7))
    late = create("Invoice export fails for the finance team", "late", "medium", old)
    service.public_message(db, late, "Thanks for flagging this. We are investigating the export failure.", old + timedelta(minutes=20), "agent:1", 1)
    service.add_note(db, late["id"], "Check the export worker logs before retrying. Coordinate with the billing team.", 1)
    waiting_start = at(working_days_back(1))
    paused = create("Need the workspace ID to investigate sign-in", "paused", "medium", waiting_start)
    service.public_message(db, paused, "Could you share your workspace ID and the error message?", waiting_start + timedelta(minutes=20), "agent:1", 1)
    paused = service.locked_ticket(db, paused["id"])
    service.change_status(db, paused, "waiting_on_customer", waiting_start + timedelta(minutes=25), "agent:1")
    friday = now.date()
    while friday.weekday() != 4 or not calendar.working(friday) or at(friday, 18) > now:
        friday -= timedelta(days=1)
    evening = create("Question about adding a second billing contact", "friday", "small", at(friday, 18), assigned=False)
    resolved_at = at(working_days_back(4), 15)
    near = create("Dashboard totals differ from the monthly report", "reopen", "medium", at(working_days_back(6)))
    service.public_message(db, near, "The reporting filter has been corrected. Please check the totals again.", at(working_days_back(6)) + timedelta(minutes=30), "agent:1", 1)
    near = service.locked_ticket(db, near["id"])
    service.change_status(db, near, "resolved", resolved_at, "agent:1")
    return [late["id"], paused["id"], evening["id"], near["id"]]


if __name__ == "__main__":
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as db:
        ids = seed(db)
    print(f"Demo ready: {len(ids)} representative tickets")
