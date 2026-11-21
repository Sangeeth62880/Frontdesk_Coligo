"""Business mutations. The API owns a transaction; ticket row locks serialize it."""
from fastapi import HTTPException

from frontdesk.business_time import Calendar, Pause, Policy, deadlines
from frontdesk.events import log_event


def locked_ticket(db, ticket_id):
    row = db.execute("SELECT * FROM tickets WHERE id = %s FOR UPDATE", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Ticket not found")
    return row


def calendar_and_policy(db, priority):
    calendar = Calendar(frozenset(row["day"] for row in db.execute("SELECT day FROM holidays")))
    row = db.execute("SELECT * FROM sla_policies WHERE priority = %s", (priority,)).fetchone()
    return calendar, Policy(row["first_reply_minutes"], row["resolve_minutes"])


def cycle_for(db, ticket_id):
    row = db.execute("SELECT * FROM resolution_cycles WHERE ticket_id = %s ORDER BY cycle_number DESC LIMIT 1", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(409, "Ticket has no resolution cycle; run the migrations")
    return row


def sla(db, ticket, now):
    calendar, policy = calendar_and_policy(db, ticket["priority"])
    cycle = cycle_for(db, ticket["id"])
    pauses = [Pause(row["paused_at"], row["resumed_at"]) for row in db.execute(
        "SELECT paused_at, resumed_at FROM ticket_pauses WHERE cycle_id = %s ORDER BY paused_at", (cycle["id"],))]
    resolution_due = deadlines(calendar, cycle["start_at"], policy, pauses, now)[1]
    if cycle["ended_at"] is not None and cycle["resolution_due_at"] is not None:
        resolution_due = cycle["resolution_due_at"]
    checked_at = cycle["ended_at"] or now
    reply_due = calendar.add(ticket["start_at"], policy.first_reply_minutes)
    resolution_breached = checked_at > resolution_due
    first_reply_breached = (ticket["first_replied_at"] or now) > reply_due
    is_late = ticket["status"] in ("open", "waiting_on_customer") and (
        resolution_breached or (cycle["cycle_number"] == 1 and ticket["first_replied_at"] is None and first_reply_breached))
    return {"first_reply_due_at": reply_due, "resolution_due_at": resolution_due,
            "cycle_number": cycle["cycle_number"], "resolution_breached": resolution_breached,
            "first_reply_breached": first_reply_breached, "is_late": is_late}



def create_ticket(db, subject, customer_email, priority, now, actor,
                  previous_ticket_id=None, customer_token=None):
    calendar, _ = calendar_and_policy(db, priority)
    start = calendar.start(now)
    if customer_token is None:
        row = db.execute("INSERT INTO tickets(subject, customer_email, priority, start_at, previous_ticket_id) VALUES (%s,%s,%s,%s,%s) RETURNING *", (subject, customer_email, priority, start, previous_ticket_id)).fetchone()
    else:
        row = db.execute("INSERT INTO tickets(subject, customer_email, priority, start_at, previous_ticket_id, customer_token) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *", (subject, customer_email, priority, start, previous_ticket_id, customer_token)).fetchone()
    db.execute("INSERT INTO resolution_cycles(ticket_id, cycle_number, opened_at, start_at) VALUES (%s,1,%s,%s)", (row["id"], now, start))
    targets = sla(db, row, now)
    log_event(db, row["id"], actor, "created", after={"priority": priority, "cycle_number": 1, "previous_ticket_id": previous_ticket_id, "resolution_due_at": targets["resolution_due_at"]})
    return row


def add_note(db, ticket_id, body, agent_id):
    locked_ticket(db, ticket_id)
    note = db.execute("INSERT INTO internal_notes(ticket_id, agent_id, body) VALUES (%s,%s,%s) RETURNING id", (ticket_id, agent_id, body)).fetchone()
    log_event(db, ticket_id, f"agent:{agent_id}", "internal_note_added", after={"note_id": note["id"]})
    return {"id": note["id"], "visibility": "internal"}


def resume(db, ticket, now, actor):
    cycle = cycle_for(db, ticket["id"])
    pause = db.execute("UPDATE ticket_pauses SET resumed_at = %s WHERE ticket_id = %s AND cycle_id = %s AND resumed_at IS NULL RETURNING id", (now, ticket["id"], cycle["id"])).fetchone()
    if pause:
        log_event(db, ticket["id"], actor, "resumed", after={"pause_id": pause["id"], "cycle_number": cycle["cycle_number"]})


def change_status(db, ticket, status, now, actor):
    old = ticket["status"]
    if old == status:
        return ticket
    if old in ("resolved", "closed"):
        raise HTTPException(409, "Use the customer reopen endpoint for completed tickets")
    cycle = cycle_for(db, ticket["id"])
    if old == "waiting_on_customer":
        resume(db, ticket, now, actor)
    if status == "waiting_on_customer":
        pause = db.execute("INSERT INTO ticket_pauses(ticket_id, cycle_id, paused_at) VALUES (%s,%s,%s) RETURNING id", (ticket["id"], cycle["id"], now)).fetchone()
        log_event(db, ticket["id"], actor, "paused", after={"pause_id": pause["id"], "cycle_number": cycle["cycle_number"]})
    targets = sla(db, ticket, now)
    if status == "resolved":
        db.execute("UPDATE resolution_cycles SET ended_at = %s, resolution_due_at = %s, breached = %s WHERE id = %s", (now, targets["resolution_due_at"], targets["resolution_breached"], cycle["id"]))
    updated = db.execute("UPDATE tickets SET status = %s, resolved_at = CASE WHEN %s = 'resolved' THEN %s ELSE resolved_at END WHERE id = %s RETURNING *", (status, status, now, ticket["id"])).fetchone()
    after = {"status": status, "cycle_number": cycle["cycle_number"]}
    if status == "resolved":
        after.update(resolution_due_at=targets["resolution_due_at"], breached=targets["resolution_breached"])
    log_event(db, ticket["id"], actor, "status_changed", before={"status": old}, after=after)
    return updated


def public_message(db, ticket, body, now, actor, agent_id=None):
    if ticket["status"] in ("resolved", "closed"):
        raise HTTPException(409, "Reopen the completed ticket before adding a reply")
    if agent_id is not None and ticket["assignee_id"] != agent_id:
        raise HTTPException(409, "Claim this ticket before replying; only its assignee can post a public agent reply")
    row = db.execute("INSERT INTO public_messages(ticket_id, author_type, agent_id, body) VALUES (%s,%s,%s,%s) RETURNING id", (ticket["id"], "agent" if agent_id is not None else "customer", agent_id, body)).fetchone()
    if agent_id is not None:
        # Database predicate ensures even simultaneous agent replies satisfy once.
        db.execute("UPDATE tickets SET first_replied_at = %s WHERE id = %s AND first_replied_at IS NULL", (now, ticket["id"]))
    log_event(db, ticket["id"], actor, "public_reply", after={"message_id": row["id"], "first_replied_at": now if agent_id is not None and ticket["first_replied_at"] is None else ticket["first_replied_at"]})
    if agent_id is None and ticket["status"] == "waiting_on_customer":
        change_status(db, ticket, "open", now, actor)
    return {"id": row["id"], "visibility": "public"}


def change_priority(db, ticket, priority, now, actor):
    if ticket["status"] in ("resolved", "closed"):
        raise HTTPException(409, "Reopen before changing the priority")
    if ticket["priority"] == priority:
        return ticket
    before = sla(db, ticket, now)
    updated = db.execute("UPDATE tickets SET priority = %s WHERE id = %s RETURNING *", (priority, ticket["id"])).fetchone()
    after = sla(db, updated, now)
    def snapshot(priority, values):
        return {"priority": priority, "cycle_number": values["cycle_number"], "first_reply_due_at": values["first_reply_due_at"], "resolution_due_at": values["resolution_due_at"]}
    log_event(db, ticket["id"], actor, "priority_changed", snapshot(ticket["priority"], before), snapshot(priority, after))
    return updated


def auto_close(db, now):
    from frontdesk.business_time import should_auto_close
    closed = []
    # Locked rows are skipped by another sweep. Each state transition and its
    # event commit together, so retries can never close the same ticket twice.
    candidates = db.execute("SELECT * FROM tickets WHERE status = 'waiting_on_customer' ORDER BY id FOR UPDATE SKIP LOCKED").fetchall()
    for ticket in candidates:
        cycle = cycle_for(db, ticket["id"])
        pause = db.execute("SELECT paused_at FROM ticket_pauses WHERE ticket_id = %s AND cycle_id = %s AND resumed_at IS NULL", (ticket["id"], cycle["id"])).fetchone()
        if not pause:
            raise HTTPException(409, "Waiting ticket is missing its active pause interval")
        calendar, _ = calendar_and_policy(db, ticket["priority"])
        if not should_auto_close(calendar, pause["paused_at"], now):
            continue
        targets = sla(db, ticket, now)
        resume(db, ticket, now, "system")
        db.execute("UPDATE resolution_cycles SET ended_at = %s, resolution_due_at = %s, breached = %s WHERE id = %s", (now, targets["resolution_due_at"], targets["resolution_breached"], cycle["id"]))
        db.execute("UPDATE tickets SET status = 'closed', closed_at = %s WHERE id = %s", (now, ticket["id"]))
        log_event(db, ticket["id"], "system", "auto_closed", before={"status": "waiting_on_customer"}, after={"status": "closed", "cycle_number": cycle["cycle_number"], "resolution_due_at": targets["resolution_due_at"], "breached": targets["resolution_breached"]})
        closed.append(ticket["id"])
    return {"closed_count": len(closed), "ticket_ids": closed}


def reopen(db, ticket, now):
    from frontdesk.business_time import plan_reopen
    if ticket["status"] not in ("resolved", "closed"):
        raise HTTPException(409, "Only completed tickets can be reopened")
    calendar, policy = calendar_and_policy(db, ticket["priority"])
    if ticket["status"] == "resolved":
        plan = plan_reopen(calendar, ticket["resolved_at"], now, policy)
    else:
        plan = None  # Auto-closed tickets become linked new requests.
    if plan is None or plan.action == "linked_new_ticket":
        new = create_ticket(db, ticket["subject"], ticket["customer_email"], ticket["priority"], now,
                            "customer", ticket["id"], ticket["customer_token"])
        return "linked_new_ticket", new
    previous = cycle_for(db, ticket["id"])
    if previous["ended_at"] is None:
        raise HTTPException(409, "Completed ticket is missing its cycle snapshot")
    number = previous["cycle_number"] + 1
    db.execute("INSERT INTO resolution_cycles(ticket_id, cycle_number, opened_at, start_at) VALUES (%s,%s,%s,%s)", (ticket["id"], number, now, plan.cycle_start))
    updated = db.execute("UPDATE tickets SET status = 'open', resolved_at = NULL, closed_at = NULL WHERE id = %s RETURNING *", (ticket["id"],)).fetchone()
    log_event(db, ticket["id"], "customer", "reopened",
              before={"status": ticket["status"], "cycle_number": previous["cycle_number"], "resolution_due_at": previous["resolution_due_at"]},
              after={"status": "open", "cycle_number": number, "start_at": plan.cycle_start, "resolution_due_at": plan.resolution_due})
    return "reopen", updated
