"""Transactional Frontdesk API. Customer capabilities and agent auth are separate."""
import os
import secrets
import hashlib
import json
import logging
import html
from datetime import datetime, timedelta, timezone
from frontdesk.auth import verify_password, token_hash
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from frontdesk.scheduler import Sweeper
from frontdesk import service
from frontdesk.business_time import CalendarRangeError, local

from pydantic import BaseModel, ConfigDict, Field, field_validator
from frontdesk.events import log_event
from frontdesk.serializers import customer_csv, customer_ticket


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Message body cannot be blank")
        return value


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=300)
    customer_email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    priority: Literal["urgent", "medium", "small"] = "medium"


class AgentTicketInput(TicketInput):
    source: Literal["customer", "agent"] = "customer"


class MessageInput(NoteInput):
    visibility: Literal["public", "internal"] = "public"


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "waiting_on_customer", "resolved", "closed"]
    body: str | None = Field(default=None, min_length=1, max_length=10000)
    version: int = Field(ge=0)


class PriorityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: Literal["urgent", "medium", "small"]


class ReassignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignee_id: int


def create_app(database_url=None, sweep_token=None, clock=None, sweep_interval=None, auth_clock=None):
    database_url = database_url or os.environ.get("DATABASE_URL")
    sweep_token = sweep_token or os.environ.get("FRONTDESK_SWEEP_TOKEN")

    interval = float(os.environ.get("FRONTDESK_SWEEP_INTERVAL_SECONDS", "60")) if sweep_interval is None else sweep_interval

    @asynccontextmanager
    async def lifespan(app):
        sweeper = Sweeper(database_url, interval) if database_url and interval > 0 else None
        if sweeper:
            sweeper.start()
        try:
            yield
        finally:
            if sweeper:
                sweeper.stop()

    app = FastAPI(title="Frontdesk", version="0.1.0", lifespan=lifespan)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path not in ("/docs", "/redoc"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'"
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Never echo request bodies (which may contain private note text).
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()]})

    @app.get("/", include_in_schema=False)
    def workspace():
        page = (static / "index.html").read_text()
        hint = ""
        if os.environ.get("FRONTDESK_SEED_DEMO", "false").lower() == "true":
            password = os.environ.get("FRONTDESK_DEMO_PASSWORD")
            if password:
                hint = '<p class="form-hint">Demo: meera@arvo.example, arun@arvo.example, divya@arvo.example · Password: ' + html.escape(password) + '</p>'
        return HTMLResponse(page.replace("<!-- DEMO_LOGIN_HINT -->", hint))

    @app.get("/customer", include_in_schema=False)
    def customer_page():
        # Fixed public shell only: no agent state, notes or tokens are embedded.
        return FileResponse(static / "customer.html")

    def connection():
        if not database_url:
            raise HTTPException(503, "DATABASE_URL is not configured")
        with psycopg.connect(database_url, row_factory=dict_row) as db:
            yield db

    DB = Annotated[psycopg.Connection, Depends(connection, scope="function")]

    @app.get("/health", include_in_schema=False)
    def health(db: DB):
        db.execute("SELECT 1")
        return {"status": "ok"}

    def customer_token(x_customer_token: Annotated[UUID | None, Header()] = None):
        if x_customer_token is None:
            raise HTTPException(401, "Customer access token required")
        return x_customer_token

    Customer = Annotated[UUID, Depends(customer_token)]

    def auth_now():
        source = auth_clock or clock
        return source() if source else datetime.now(timezone.utc)

    class LoginInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        email: str = Field(max_length=320)
        password: str = Field(max_length=1024)

    @app.post("/auth/login", tags=["auth"])
    def login(data: LoginInput, db: DB):
        email = data.email.strip().lower()
        # Serialize attempts for the same normalized email across all instances.
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))", (email,))
        instant = auth_now()
        attempt = db.execute("SELECT * FROM agent_login_attempts WHERE email=%s", (email,)).fetchone()
        row = db.execute("SELECT id, name, password_hash, is_active FROM agents WHERE email=%s", (email,)).fetchone()
        valid = verify_password(data.password, row["password_hash"] if row else None)
        if attempt and attempt["locked_until"] and instant < attempt["locked_until"]:
            logging.getLogger("frontdesk.auth").warning(json.dumps({"event": "agent_login", "outcome": "throttled"}))
            return JSONResponse(status_code=429, content={"detail": "Too many sign-in attempts. Try again later."}, headers={"Retry-After": str(max(1, int((attempt["locked_until"]-instant).total_seconds())))})
        if not row or not row["is_active"] or not row["password_hash"] or not valid:
            failures = 1
            start = instant
            if attempt and instant < attempt["window_start"] + timedelta(minutes=10) and not attempt["locked_until"]:
                failures = attempt["failures"] + 1
                start = attempt["window_start"]
            locked = instant + timedelta(minutes=10) if failures >= 5 else None
            db.execute("""INSERT INTO agent_login_attempts(email, failures, window_start, locked_until) VALUES (%s,%s,%s,%s)
                ON CONFLICT (email) DO UPDATE SET failures=EXCLUDED.failures, window_start=EXCLUDED.window_start, locked_until=EXCLUDED.locked_until""", (email, failures, start, locked))
            logging.getLogger("frontdesk.auth").warning(json.dumps({"event": "agent_login", "outcome": "failed"}))
            # Return, rather than raise, so the failure counter commits.
            return JSONResponse(status_code=401, content={"detail": "Invalid email or password"})
        db.execute("DELETE FROM agent_login_attempts WHERE email=%s", (email,))
        raw = secrets.token_hex(32)
        expires = instant + timedelta(hours=12)
        db.execute("INSERT INTO agent_sessions(agent_id, token_hash, created_at, expires_at) VALUES (%s,%s,%s,%s)", (row["id"], token_hash(raw), instant, expires))
        return {"token": raw, "expires_at": expires, "agent": {"id": row["id"], "name": row["name"]}}

    def session_agent(db: DB, authorization: Annotated[str | None, Header()] = None):
        raw = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if len(raw) != 64 or any(c not in "0123456789abcdef" for c in raw):
            raise HTTPException(401, "Agent authentication required")
        row = db.execute("""SELECT a.id, a.name FROM agent_sessions s JOIN agents a ON a.id=s.agent_id
            WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>%s AND a.is_active""", (token_hash(raw), auth_now())).fetchone()
        if not row:
            raise HTTPException(401, "Agent authentication required")
        return row

    SessionAgent = Annotated[dict, Depends(session_agent)]

    @app.get("/auth/me", tags=["auth"])
    def me(actor: SessionAgent):
        return actor

    @app.post("/auth/logout", tags=["auth"])
    def logout(db: DB, actor: SessionAgent, authorization: Annotated[str, Header()]):
        db.execute("UPDATE agent_sessions SET revoked_at=%s WHERE token_hash=%s", (auth_now(), token_hash(authorization[7:])))
        return {"ok": True}

    Agent = SessionAgent

    def ticket_for_customer(db, ticket_id, token):
        row = db.execute("SELECT * FROM tickets WHERE id = %s AND customer_token = %s", (ticket_id, token)).fetchone()
        if not row:
            raise HTTPException(404, "Ticket not found")
        return row

    @app.get("/customer/tickets", tags=["customer"])
    def customer_list(db: DB, token: Customer):
        rows = db.execute("SELECT * FROM tickets WHERE customer_token = %s ORDER BY id", (token,)).fetchall()
        return [customer_ticket(row) for row in rows]

    @app.get("/customer/tickets/{ticket_id}", tags=["customer"])
    def customer_view(ticket_id: int, db: DB, token: Customer):
        ticket = ticket_for_customer(db, ticket_id, token)
        messages = db.execute("SELECT id, author_type, body, created_at FROM public_messages WHERE ticket_id = %s ORDER BY created_at, id", (ticket_id,)).fetchall()
        return customer_ticket(ticket, messages)

    @app.get("/export.csv", response_class=PlainTextResponse, tags=["customer"])
    def export(db: DB, token: Customer):
        rows = db.execute("SELECT * FROM tickets WHERE customer_token = %s ORDER BY id", (token,)).fetchall()
        return PlainTextResponse(customer_csv(rows), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tickets.csv"})

    @app.post("/tickets/{ticket_id}/notes", status_code=201)
    def note(ticket_id: int, data: NoteInput, db: DB, actor: Agent):
        return service.add_note(db, ticket_id, data.body, actor["id"])

    @app.post("/tickets/{ticket_id}/claim")
    def claim(ticket_id: int, db: DB, actor: Agent):
        # Atomic compare-and-set. Never pre-read the assignee before this write.
        won = db.execute(
            "UPDATE tickets SET assignee_id = %s WHERE id = %s AND assignee_id IS NULL AND status IN ('open', 'waiting_on_customer') RETURNING id, assignee_id",
            (actor["id"], ticket_id),
        ).fetchone()
        if won:
            log_event(db, ticket_id, f"agent:{actor['id']}", "claimed", before={"assignee_id": None}, after={"assignee_id": actor["id"]})
            return won
        current = db.execute("SELECT t.id, t.status, t.assignee_id, a.name AS assignee_name FROM tickets t LEFT JOIN agents a ON a.id = t.assignee_id WHERE t.id = %s", (ticket_id,)).fetchone()
        if not current:
            raise HTTPException(404, "Ticket not found")
        if current["assignee_id"] == actor["id"] and current["status"] in ("open", "waiting_on_customer"):
            return {"id": ticket_id, "assignee_id": actor["id"]}
        raise HTTPException(409, detail={"message": "Ticket is already claimed or inactive", **current})

    def now(db):
        return local(clock()) if clock is not None else db.execute("SELECT clock_timestamp() AS now").fetchone()["now"]

    @app.exception_handler(CalendarRangeError)
    async def calendar_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/agents")
    def agents(db: DB, actor: Agent):
        return db.execute("SELECT id, name FROM agents ORDER BY id").fetchall()

    @app.post("/tickets", status_code=201)
    def create(data: AgentTicketInput, db: DB, actor: Agent):
        ticket = service.create_ticket(db, data.subject, data.customer_email, data.priority, now(db), f"agent:{actor['id']}", source=data.source)
        return {**customer_ticket(ticket), "customer_token": str(ticket["customer_token"])}

    @app.post("/customer/tickets", status_code=201, tags=["customer"])
    def customer_create(data: TicketInput, db: DB):
        ticket = service.create_ticket(db, data.subject, data.customer_email, data.priority, now(db), "customer")
        return {**customer_ticket(ticket), "customer_token": str(ticket["customer_token"])}

    def sla_view(db, ticket):
        targets = service.sla(db, ticket, now(db))
        return {**ticket, **{key: targets[key] for key in (
            "first_reply_due_at", "first_reply_breached", "resolution_breached")}, "sla": targets}

    def agent_view(db, ticket):
        ticket = service.locked_ticket(db, ticket["id"])
        messages = db.execute("SELECT id, author_type, agent_id, body, created_at, 'public' AS visibility FROM public_messages WHERE ticket_id = %s ORDER BY created_at, id", (ticket["id"],)).fetchall()
        notes = db.execute("SELECT id, agent_id, body, created_at, 'internal' AS visibility FROM internal_notes WHERE ticket_id = %s ORDER BY created_at, id", (ticket["id"],)).fetchall()
        first_reply = db.execute("SELECT actor, after_value->>'first_replied_at' AS at FROM events WHERE ticket_id = %s AND event_type = 'public_reply' AND actor LIKE 'agent:%%' ORDER BY id LIMIT 1", (ticket["id"],)).fetchone()
        return {**sla_view(db, ticket), "first_reply_at": first_reply["at"] if first_reply else None, "first_reply_actor": first_reply["actor"] if first_reply else None, "messages": messages, "internal_notes": notes}

    @app.get("/tickets")
    def ticket_list(db: DB, actor: Agent, assignee: Literal["me", "all", "unassigned"] = "me"):
        where = {"me": "assignee_id = %s", "all": "true", "unassigned": "assignee_id IS NULL"}[assignee]
        rows = db.execute("SELECT * FROM tickets WHERE " + where + " ORDER BY id FOR UPDATE", (actor["id"],) if assignee == "me" else ()).fetchall()
        result = [sla_view(db, ticket) for ticket in rows]
        return sorted(result, key=lambda t: (not t["sla"]["is_late"], t["id"]))

    @app.get("/tickets/{ticket_id}")
    def ticket_view(ticket_id: int, db: DB, actor: Agent):
        row = db.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Ticket not found")
        return agent_view(db, row)

    @app.get("/tickets/{ticket_id}/events")
    def events(ticket_id: int, db: DB, actor: Agent):
        if not db.execute("SELECT id FROM tickets WHERE id = %s", (ticket_id,)).fetchone():
            raise HTTPException(404, "Ticket not found")
        return db.execute("SELECT id, actor, event_type, before_value, after_value, created_at FROM events WHERE ticket_id = %s ORDER BY id", (ticket_id,)).fetchall()

    def idempotent(db, actor, key, path, data, mutation):
        if key is None:
            return mutation()
        fingerprint = hashlib.sha256(json.dumps([path, data.model_dump()], sort_keys=True).encode()).hexdigest()
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (actor + ":" + key,))
        old = db.execute("SELECT * FROM request_idempotency WHERE actor = %s AND key = %s AND created_at >= clock_timestamp() - interval '24 hours'", (actor, key)).fetchone()
        if old:
            if old["fingerprint"] != fingerprint:
                raise HTTPException(409, "Idempotency key already used for a different request")
            return old["response"]
        result = mutation()
        db.execute("""INSERT INTO request_idempotency(actor, key, fingerprint, response) VALUES (%s,%s,%s,%s)
            ON CONFLICT (actor,key) DO UPDATE SET fingerprint=EXCLUDED.fingerprint, response=EXCLUDED.response, created_at=clock_timestamp()""",
            (actor, key, fingerprint, Jsonb(result)))
        return result

    @app.post("/tickets/{ticket_id}/messages", status_code=201)
    def message(ticket_id: int, data: MessageInput, db: DB, actor: Agent,
                idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
        def mutation():
            if data.visibility == "internal":
                return service.add_note(db, ticket_id, data.body, actor["id"])
            ticket = service.locked_ticket(db, ticket_id)
            return service.public_message(db, ticket, data.body, now(db), f"agent:{actor['id']}", actor["id"])
        return idempotent(db, f"agent:{actor['id']}", idempotency_key, f"/tickets/{ticket_id}/messages", data, mutation)

    @app.post("/tickets/{ticket_id}/customer-reply", status_code=201, tags=["customer"])
    def customer_reply(ticket_id: int, data: NoteInput, db: DB, token: Customer,
                       idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
        ticket_for_customer(db, ticket_id, token)
        def mutation():
            ticket = service.locked_ticket(db, ticket_id)
            action = None
            if ticket["status"] in ("resolved", "closed"):
                action, ticket = service.reopen(db, ticket, now(db))
            result = service.public_message(db, ticket, data.body, now(db), "customer")
            return {**result, "ticket_id": ticket["id"], "action": action}
        return idempotent(db, f"customer:{token}", idempotency_key, f"/tickets/{ticket_id}/customer-reply", data, mutation)

    @app.post("/tickets/{ticket_id}/status")
    def status(ticket_id: int, data: StatusInput, db: DB, actor: Agent):
        ticket = service.locked_ticket(db, ticket_id)
        if ticket["version"] != data.version:
            raise HTTPException(409, "Ticket changed; refresh and retry with its current version")
        if data.status == "waiting_on_customer":
            if not data.body or not data.body.strip():
                raise HTTPException(422, "Waiting requires a public agent message in the same request")
            if ticket["status"] != "open":
                raise HTTPException(409, "Only open tickets can start waiting")
            service.public_message(db, ticket, data.body, now(db), f"agent:{actor['id']}", actor["id"])
        if data.status == "open" and ticket["status"] == "resolved":
            action, updated = service.reopen(db, ticket, now(db), f"agent:{actor['id']}")
            return {**customer_ticket(updated), "version": updated["version"], "action": action, "sla": service.sla(db, updated, now(db))}
        updated = service.change_status(db, ticket, data.status, now(db), f"agent:{actor['id']}")
        return {**customer_ticket(updated), "version": updated["version"], "sla": service.sla(db, updated, now(db))}

    @app.post("/tickets/{ticket_id}/priority")
    def priority(ticket_id: int, data: PriorityInput, db: DB, actor: Agent):
        ticket = service.locked_ticket(db, ticket_id)
        updated = service.change_priority(db, ticket, data.priority, now(db), f"agent:{actor['id']}")
        return {**customer_ticket(updated), "version": updated["version"], "sla": service.sla(db, updated, now(db))}

    @app.post("/tickets/{ticket_id}/agent-reopen")
    def agent_reopen(ticket_id: int, response: Response, db: DB, actor: Agent):
        ticket = service.locked_ticket(db, ticket_id)
        action, updated = service.reopen(db, ticket, now(db), f"agent:{actor['id']}")
        response.status_code = 201 if action == "linked_new_ticket" else 200
        return {"action": action, "ticket": customer_ticket(updated), "sla": service.sla(db, updated, now(db))}

    @app.post("/tickets/{ticket_id}/reassign")
    def reassign(ticket_id: int, data: ReassignInput, db: DB, actor: Agent):
        ticket = service.locked_ticket(db, ticket_id)
        if ticket["status"] not in ("open", "waiting_on_customer"):
            raise HTTPException(409, "Only active tickets can be reassigned")
        if not db.execute("SELECT id FROM agents WHERE id = %s", (data.assignee_id,)).fetchone():
            raise HTTPException(422, "Unknown assignee")
        if ticket["assignee_id"] != data.assignee_id:
            db.execute("UPDATE tickets SET assignee_id = %s WHERE id = %s", (data.assignee_id, ticket_id))
            log_event(db, ticket_id, f"agent:{actor['id']}", "reassigned", before={"assignee_id": ticket["assignee_id"]}, after={"assignee_id": data.assignee_id})
        return {"id": ticket_id, "assignee_id": data.assignee_id}

    @app.post("/admin/sweep")
    def sweep(db: DB, authorization: Annotated[str | None, Header()] = None):
        if not sweep_token or not authorization or not secrets.compare_digest(authorization, f"Bearer {sweep_token}"):
            raise HTTPException(401, "Sweep authentication required")
        return service.auto_close(db, now(db))

    @app.post("/tickets/{ticket_id}/reopen", tags=["customer"])
    def reopen_ticket(ticket_id: int, response: Response, db: DB, token: Customer):
        ticket_for_customer(db, ticket_id, token)
        ticket = service.locked_ticket(db, ticket_id)
        action, updated = service.reopen(db, ticket, now(db))
        response.status_code = 201 if action == "linked_new_ticket" else 200
        return {"action": action, "ticket": customer_ticket(updated), "sla": service.sla(db, updated, now(db))}

    return app


app = create_app()
