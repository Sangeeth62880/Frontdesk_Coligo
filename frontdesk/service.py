"""Business mutations. The API owns a transaction; ticket row locks serialize it."""
from fastapi import HTTPException

from frontdesk.business_time import Calendar, Pause, Policy, deadlines, local
from frontdesk.events import log_event


def locked_ticket(db, ticket_id):
    row = db.execute("SELECT * FROM tickets WHERE id = %s FOR UPDATE", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Ticket not found")
    return row


def require_assignee(ticket, agent_id):
    if ticket['assignee_id'] != agent_id:
        raise HTTPException(409, 'Claim this ticket first; only its assignee can make this change')


def calendar_and_policy(db, priority):
    calendar = Calendar(frozenset(row["day"] for row in db.execute("SELECT day FROM holidays")))
    row = db.execute("SELECT * FROM sla_policies WHERE priority = %s", (priority,)).fetchone()
    return calendar, Policy(row["first_reply_minutes"], row["resolve_minutes"])


def cycle_for(db, ticket_id):
    row = db.execute("SELECT * FROM resolution_cycles WHERE ticket_id = %s ORDER BY cycle_number DESC LIMIT 1", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(409, "Ticket has no resolution cycle; run the migrations")
    return row


def load_sla_context(db, tickets):
    """Prefetch the calendar and histories after the caller locks its ticket rows."""
    ids = [ticket["id"] for ticket in tickets]
    calendar = Calendar(frozenset(row["day"] for row in db.execute("SELECT day FROM holidays")))
    policies = {row["priority"]: Policy(row["first_reply_minutes"], row["resolve_minutes"]) for row in db.execute("SELECT * FROM sla_policies")}
    histories = db.execute("SELECT * FROM resolution_cycles WHERE ticket_id = ANY(%s) ORDER BY cycle_number", (ids,)).fetchall()
    latest = {}
    initial = {}
    for cycle in histories:
        latest[cycle["ticket_id"]] = cycle
        if cycle["cycle_number"] == 1:
            initial[cycle["ticket_id"]] = cycle
    pauses: dict[int, list[Pause]] = {}
    for row in db.execute("SELECT * FROM ticket_pauses WHERE ticket_id = ANY(%s) ORDER BY paused_at", (ids,)):
        pauses.setdefault(row["cycle_id"], []).append(Pause(row["paused_at"], row["resumed_at"]))
    return {"calendar": calendar, "policies": policies, "latest": latest, "initial": initial, "pauses": pauses, "histories": histories}


def sla(db, ticket, now, *, context=None):
    now = local(now)
    if context is None:
        ticket = locked_ticket(db, ticket["id"])
        calendar, policy = calendar_and_policy(db, ticket["priority"])
        cycle = cycle_for(db, ticket["id"])
        pauses = [Pause(row["paused_at"], row["resumed_at"]) for row in db.execute(
            "SELECT paused_at, resumed_at FROM ticket_pauses WHERE cycle_id = %s ORDER BY paused_at", (cycle["id"],))]
        initial = db.execute("SELECT ended_at FROM resolution_cycles WHERE ticket_id = %s AND cycle_number = 1", (ticket["id"],)).fetchone()
    else:
        # The list query already holds these exact rows FOR UPDATE.
        calendar, policy = context["calendar"], context["policies"][ticket["priority"]]
        cycle = context["latest"].get(ticket["id"])
        if cycle is None:
            raise HTTPException(409, "Ticket has no resolution cycle; run the migrations")
        pauses = context["pauses"].get(cycle["id"], [])
        initial = context["initial"][ticket["id"]]
    resolution_due = deadlines(calendar, cycle["start_at"], policy, pauses, now)[1]
    if cycle["ended_at"] is not None and cycle["resolution_due_at"] is not None:
        resolution_due = cycle["resolution_due_at"]
    checked_at = cycle["ended_at"] or now
    reply_due = calendar.add(ticket["start_at"], policy.first_reply_minutes) if ticket["first_reply_required"] else None
    # Completion freezes both obligations. History and prior priority breaches stick.
    reply_checked = min(value for value in (ticket["first_replied_at"], initial["ended_at"], now) if value is not None)
    reply_breached = bool(reply_due and reply_checked > reply_due)
    resolution_breached = bool(cycle["breached"] or checked_at > resolution_due)
    if cycle["ended_at"] is None and (cycle["breached"] != resolution_breached or (resolution_breached and cycle["breach_due_at"] is None and checked_at > resolution_due)):
        db.execute("UPDATE resolution_cycles SET breached = %s, breach_due_at = COALESCE(breach_due_at, CASE WHEN %s THEN %s END) WHERE id = %s", (resolution_breached, checked_at > resolution_due, resolution_due, cycle["id"]))
    flags = {"first_reply_breached": ticket["first_reply_breached"] or reply_breached,
             "resolution_breached": ticket["resolution_breached"] or resolution_breached}
    if (ticket["first_reply_due_at"] != reply_due or
            any(ticket[key] != value for key, value in flags.items()) or (reply_breached and ticket["first_reply_breach_due_at"] is None)):
        db.execute("""UPDATE tickets SET first_reply_breached=%s,
            resolution_breached=%s, first_reply_due_at=%s, first_reply_breach_due_at=COALESCE(first_reply_breach_due_at,CASE WHEN %s THEN %s END) WHERE id=%s""",
            (flags["first_reply_breached"], flags["resolution_breached"], reply_due, reply_breached, reply_due, ticket["id"]))
    return {"first_reply_due_at": reply_due, "resolution_due_at": resolution_due,
            "cycle_number": cycle["cycle_number"], "cycle_resolution_breached": resolution_breached, **flags,
            "breached_targets": [name for name in ("first_reply", "resolution") if flags[name + "_breached"]],
            "is_late": any(flags.values())}



def late_targets(db, ticket, targets, now, *, context=None):
    """Working-time overshoot against retained breach deadlines, per cycle."""
    if not targets['is_late']:
        return []
    context = context or load_sla_context(db,[ticket])
    calendar = context['calendar']
    cycles = [cycle for cycle in context['histories'] if cycle['ticket_id']==ticket['id']]
    result = []
    def record(target, number, due, stop, pauses=()):
        minutes = None
        if due is not None and due <= stop:
            minutes = calendar.minutes(due,stop)
            for pause in pauses:
                begin, end = max(due,pause.paused_at), min(stop,pause.resumed_at or now)
                if begin < end:
                    minutes -= calendar.minutes(begin,end)
            minutes = round(max(0,minutes),6)
        result.append({'target':target,'cycle_number':number,'due_at':due,'working_minutes':minutes})
    if targets['first_reply_breached']:
        initial = context['initial'][ticket['id']]
        stop = min(value for value in (ticket['first_replied_at'],initial['ended_at'],now) if value is not None)
        due = ticket['first_reply_breach_due_at'] or targets['first_reply_due_at']
        record('first_reply',1,due,stop)
    for cycle in cycles:
        current = cycle['cycle_number']==targets['cycle_number']
        if cycle['breached'] or (current and targets['cycle_resolution_breached']):
            due = cycle['breach_due_at'] or cycle['resolution_due_at'] or (targets['resolution_due_at'] if current else None)
            record('resolution',cycle['cycle_number'],due,min(now,cycle['ended_at'] or now),context['pauses'].get(cycle['id'],[]))
    if targets['resolution_breached'] and not any(row['target']=='resolution' for row in result):
        record('resolution',None,None,now)
    return result


def create_ticket(db, subject, customer_email, priority, now, actor,
                  previous_ticket_id=None, customer_token=None, *, source=None, body=None):
    calendar, _ = calendar_and_policy(db, priority)
    start = calendar.start(now)
    if customer_token is None:
        row = db.execute("INSERT INTO tickets(subject, customer_email, priority, start_at, previous_ticket_id, created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *", (subject, customer_email, priority, start, previous_ticket_id, now)).fetchone()
    else:
        row = db.execute("INSERT INTO tickets(subject, customer_email, priority, start_at, previous_ticket_id, customer_token, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *", (subject, customer_email, priority, start, previous_ticket_id, customer_token, now)).fetchone()
    db.execute("INSERT INTO resolution_cycles(ticket_id, cycle_number, opened_at, start_at) VALUES (%s,1,%s,%s)", (row["id"], now, start))
    # Existing internal callers (including reopen) retain their intake behavior.
    source = source or ("agent" if actor.startswith("agent:") else "customer")
    if source == "agent":
        row = db.execute("UPDATE tickets SET first_reply_required = false WHERE id = %s RETURNING *", (row["id"],)).fetchone()
    description = db.execute("INSERT INTO public_messages(ticket_id,author_type,body,created_at) VALUES (%s,'customer',%s,%s) RETURNING id", (row['id'],body,row['created_at'])).fetchone() if body is not None else None
    targets = sla(db, row, now)
    log_event(db, row["id"], actor, "created", after={"message_id": description["id"] if description else None, "source": source, "priority": priority, "cycle_number": 1, "previous_ticket_id": previous_ticket_id, "resolution_due_at": targets["resolution_due_at"]}, at=now)
    return row


def add_note(db, ticket_id, body, agent_id, *, now=None):
    ticket = locked_ticket(db, ticket_id)
    if ticket["status"] == "closed":
        raise HTTPException(409, "Closed tickets cannot be edited")
    note = db.execute("INSERT INTO internal_notes(ticket_id, agent_id, body, created_at) VALUES (%s,%s,%s,COALESCE(%s,clock_timestamp())) RETURNING id", (ticket_id, agent_id, body, now)).fetchone()
    log_event(db, ticket_id, f"agent:{agent_id}", "internal_note_added", after={"note_id": note["id"]}, at=now)
    return {"id": note["id"], "visibility": "internal"}


def resume(db, ticket, now, actor):
    cycle = cycle_for(db, ticket["id"])
    pause = db.execute("UPDATE ticket_pauses SET resumed_at = %s WHERE ticket_id = %s AND cycle_id = %s AND resumed_at IS NULL RETURNING id", (now, ticket["id"], cycle["id"])).fetchone()
    if pause:
        log_event(db, ticket["id"], actor, "resumed", after={"pause_id": pause["id"], "cycle_number": cycle["cycle_number"]}, at=now)


def change_status(db, ticket, status, now, actor):
    old = ticket["status"]
    if (old, status) not in {("open", "waiting_on_customer"), ("waiting_on_customer", "open"), ("open", "resolved"), ("waiting_on_customer", "resolved")}:
        raise HTTPException(409, f"Transition {old} -> {status} is not allowed; completed tickets require reopening and closing is system-only")
    cycle = cycle_for(db, ticket["id"])
    sla(db, ticket, now)
    if old == "waiting_on_customer":
        resume(db, ticket, now, actor)
    if status == "waiting_on_customer":
        pause = db.execute("INSERT INTO ticket_pauses(ticket_id, cycle_id, paused_at) VALUES (%s,%s,%s) RETURNING id", (ticket["id"], cycle["id"], now)).fetchone()
        log_event(db, ticket["id"], actor, "paused", after={"pause_id": pause["id"], "cycle_number": cycle["cycle_number"]}, at=now)
    targets = sla(db, ticket, now)
    if status == "resolved":
        db.execute("UPDATE resolution_cycles SET ended_at = %s, resolution_due_at = %s, breached = %s WHERE id = %s", (now, targets["resolution_due_at"], targets["cycle_resolution_breached"], cycle["id"]))
    updated = db.execute("UPDATE tickets SET status = %s, resolved_at = CASE WHEN %s = 'resolved' THEN %s ELSE resolved_at END WHERE id = %s RETURNING *", (status, status, now, ticket["id"])).fetchone()
    after = {"status": status, "cycle_number": cycle["cycle_number"]}
    if status == "resolved":
        after.update(resolution_due_at=targets["resolution_due_at"], breached=targets["cycle_resolution_breached"])
    log_event(db, ticket["id"], actor, "status_changed", before={"status": old}, after=after, at=now)
    return updated


def public_message(db, ticket, body, now, actor, agent_id=None):
    if ticket["status"] in ("resolved", "closed"):
        raise HTTPException(409, "Reopen the completed ticket before adding a reply")
    if agent_id is not None and ticket["assignee_id"] != agent_id:
        raise HTTPException(409, "Claim this ticket before replying; only its assignee can post a public agent reply")
    sla(db, ticket, now)
    row = db.execute("INSERT INTO public_messages(ticket_id, author_type, agent_id, body, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING id", (ticket["id"], "agent" if agent_id is not None else "customer", agent_id, body, now)).fetchone()
    if agent_id is not None:
        # Database predicate ensures even simultaneous agent replies satisfy once.
        db.execute("UPDATE tickets SET first_replied_at = %s WHERE id = %s AND first_replied_at IS NULL", (now, ticket["id"]))
    log_event(db, ticket["id"], actor, "public_reply", after={"message_id": row["id"], "first_replied_at": now if agent_id is not None and ticket["first_replied_at"] is None else ticket["first_replied_at"]}, at=now)
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
    log_event(db, ticket["id"], actor, "priority_changed", snapshot(ticket["priority"], before), snapshot(priority, after), at=now)
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
        db.execute("UPDATE resolution_cycles SET ended_at = %s, resolution_due_at = %s, breached = %s WHERE id = %s", (now, targets["resolution_due_at"], targets["cycle_resolution_breached"], cycle["id"]))
        db.execute("UPDATE tickets SET status = 'closed', closed_at = %s WHERE id = %s", (now, ticket["id"]))
        log_event(db, ticket["id"], "system", "auto_closed", before={"status": "waiting_on_customer"}, after={"status": "closed", "cycle_number": cycle["cycle_number"], "resolution_due_at": targets["resolution_due_at"], "breached": targets["cycle_resolution_breached"]}, at=now)
        closed.append(ticket["id"])
    return {"closed_count": len(closed), "ticket_ids": closed}


def reopen(db, ticket, now, actor="customer"):
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
                            actor, ticket["id"], ticket["customer_token"])
        log_event(db, new["id"], actor, "linked_ticket_created", after={"previous_ticket_id": ticket["id"]}, at=now)
        return "linked_new_ticket", new
    previous = cycle_for(db, ticket["id"])
    if previous["ended_at"] is None:
        raise HTTPException(409, "Completed ticket is missing its cycle snapshot")
    number = previous["cycle_number"] + 1
    db.execute("INSERT INTO resolution_cycles(ticket_id, cycle_number, opened_at, start_at) VALUES (%s,%s,%s,%s)", (ticket["id"], number, now, plan.cycle_start))
    updated = db.execute("UPDATE tickets SET status = 'open', resolved_at = NULL, closed_at = NULL WHERE id = %s RETURNING *", (ticket["id"],)).fetchone()
    log_event(db, ticket["id"], actor, "reopened",
              before={"status": ticket["status"], "cycle_number": previous["cycle_number"], "resolution_due_at": previous["resolution_due_at"]},
              after={"status": "open", "cycle_number": number, "start_at": plan.cycle_start, "resolution_due_at": plan.resolution_due}, at=now)
    return "reopen", updated
