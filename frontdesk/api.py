"""Transactional Frontdesk API. Customer capabilities and agent auth are separate."""
import os
import secrets
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import PlainTextResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from frontdesk.scheduler import Sweeper
from frontdesk import service
from frontdesk.business_time import CalendarRangeError, local

from pydantic import BaseModel, ConfigDict, Field
from frontdesk.events import log_event
from frontdesk.serializers import customer_csv, customer_ticket


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=20000)


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=300)
    customer_email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    priority: Literal["urgent", "medium", "small"] = "medium"


class MessageInput(NoteInput):
    visibility: Literal["public", "internal"] = "public"


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "waiting_on_customer", "resolved"]


class PriorityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: Literal["urgent", "medium", "small"]


def create_app(database_url=None, agent_token=None, sweep_token=None, clock=None, sweep_interval=None):
    database_url = database_url or os.environ.get("DATABASE_URL")
    agent_token = agent_token or os.environ.get("FRONTDESK_AGENT_TOKEN")
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
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def workspace():
        return FileResponse(static / "index.html")

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

    def agent(db: DB, authorization: Annotated[str | None, Header()] = None,
              x_agent_id: Annotated[int | None, Header()] = None):
        if not agent_token or not authorization or not secrets.compare_digest(authorization, f"Bearer {agent_token}"):
            raise HTTPException(401, "Agent authentication required")
        if x_agent_id is None:
            raise HTTPException(401, "X-Agent-Id required")
        row = db.execute("SELECT id, name FROM agents WHERE id = %s", (x_agent_id,)).fetchone()
        if not row:
            raise HTTPException(401, "Unknown agent")
        return row

    Agent = Annotated[dict, Depends(agent)]

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
    def create(data: TicketInput, db: DB, actor: Agent):
        ticket = service.create_ticket(db, data.subject, data.customer_email, data.priority, now(db), f"agent:{actor['id']}")
        return {**customer_ticket(ticket), "customer_token": str(ticket["customer_token"])}

    def agent_view(db, ticket):
        messages = db.execute("SELECT id, author_type, agent_id, body, created_at, 'public' AS visibility FROM public_messages WHERE ticket_id = %s ORDER BY created_at, id", (ticket["id"],)).fetchall()
        notes = db.execute("SELECT id, agent_id, body, created_at, 'internal' AS visibility FROM internal_notes WHERE ticket_id = %s ORDER BY created_at, id", (ticket["id"],)).fetchall()
        return {**ticket, "messages": messages, "internal_notes": notes, "sla": service.sla(db, ticket, now(db))}

    @app.get("/tickets")
    def ticket_list(db: DB, actor: Agent, assignee: Literal["me", "all", "unassigned"] = "me"):
        where = {"me": "assignee_id = %s", "all": "true", "unassigned": "assignee_id IS NULL"}[assignee]
        rows = db.execute("SELECT * FROM tickets WHERE " + where + " ORDER BY id", (actor["id"],) if assignee == "me" else ()).fetchall()
        result = [{**ticket, "sla": service.sla(db, ticket, now(db))} for ticket in rows]
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

    @app.post("/tickets/{ticket_id}/messages", status_code=201)
    def message(ticket_id: int, data: MessageInput, db: DB, actor: Agent):
        if data.visibility == "internal":
            return service.add_note(db, ticket_id, data.body, actor["id"])
        ticket = service.locked_ticket(db, ticket_id)
        return service.public_message(db, ticket, data.body, now(db), f"agent:{actor['id']}", actor["id"])

    @app.post("/tickets/{ticket_id}/customer-reply", status_code=201, tags=["customer"])
    def customer_reply(ticket_id: int, data: NoteInput, db: DB, token: Customer):
        ticket_for_customer(db, ticket_id, token)
        ticket = service.locked_ticket(db, ticket_id)
        return service.public_message(db, ticket, data.body, now(db), "customer")

    @app.post("/tickets/{ticket_id}/status")
    def status(ticket_id: int, data: StatusInput, db: DB, actor: Agent):
        ticket = service.locked_ticket(db, ticket_id)
        updated = service.change_status(db, ticket, data.status, now(db), f"agent:{actor['id']}")
        return {**customer_ticket(updated), "sla": service.sla(db, updated, now(db))}

    @app.post("/tickets/{ticket_id}/priority")
    def priority(ticket_id: int, data: PriorityInput, db: DB, actor: Agent):
        ticket = service.locked_ticket(db, ticket_id)
        updated = service.change_priority(db, ticket, data.priority, now(db), f"agent:{actor['id']}")
        return {**customer_ticket(updated), "sla": service.sla(db, updated, now(db))}

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
