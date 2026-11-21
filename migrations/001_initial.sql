CREATE TABLE agents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    email text NOT NULL UNIQUE
);
CREATE TABLE holidays (day date PRIMARY KEY, name text NOT NULL);
CREATE TABLE sla_policies (
    priority text PRIMARY KEY CHECK (priority IN ('urgent', 'medium', 'small')),
    first_reply_minutes integer NOT NULL CHECK (first_reply_minutes > 0),
    resolve_minutes integer CHECK (resolve_minutes > 0),
    CHECK ((priority = 'urgent') = (resolve_minutes IS NULL))
);
CREATE TABLE tickets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject text NOT NULL CHECK (length(trim(subject)) > 0),
    customer_email text NOT NULL,
    priority text NOT NULL REFERENCES sla_policies(priority),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'waiting_on_customer', 'resolved', 'closed')),
    assignee_id bigint REFERENCES agents(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    start_at timestamptz NOT NULL,
    first_replied_at timestamptz,
    resolved_at timestamptz,
    closed_at timestamptz,
    previous_ticket_id bigint REFERENCES tickets(id)
);
-- Customer data lives separately: no visibility predicate can accidentally expose notes.
CREATE TABLE public_messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id bigint NOT NULL REFERENCES tickets(id),
    author_type text NOT NULL CHECK (author_type IN ('agent', 'customer')),
    agent_id bigint REFERENCES agents(id),
    body text NOT NULL CHECK (length(trim(body)) > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((author_type = 'agent') = (agent_id IS NOT NULL))
);
CREATE TABLE internal_notes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id bigint NOT NULL REFERENCES tickets(id),
    agent_id bigint NOT NULL REFERENCES agents(id),
    body text NOT NULL CHECK (length(trim(body)) > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE ticket_pauses (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id bigint NOT NULL REFERENCES tickets(id),
    paused_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resumed_at timestamptz,
    CHECK (resumed_at IS NULL OR resumed_at >= paused_at)
);
CREATE UNIQUE INDEX one_open_pause_per_ticket ON ticket_pauses(ticket_id) WHERE resumed_at IS NULL;
CREATE TABLE events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id bigint NOT NULL REFERENCES tickets(id),
    actor text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'created', 'claimed', 'public_reply', 'internal_note_added', 'status_changed',
        'priority_changed', 'paused', 'resumed', 'auto_closed', 'reopened')),
    before_value jsonb,
    after_value jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION protect_events() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Events are append-only';
END;
$$;
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION protect_events();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON events
    FOR EACH STATEMENT EXECUTE FUNCTION protect_events();
CREATE FUNCTION stamp_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.created_at := clock_timestamp();
    RETURN NEW;
END;
$$;
CREATE TRIGGER events_server_timestamp BEFORE INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION stamp_event();
CREATE INDEX tickets_queue ON tickets(assignee_id, status);
CREATE INDEX public_thread ON public_messages(ticket_id, created_at, id);
CREATE INDEX internal_thread ON internal_notes(ticket_id, created_at, id);
CREATE INDEX ticket_timeline ON events(ticket_id, created_at, id);
CREATE INDEX ticket_pause_history ON ticket_pauses(ticket_id, paused_at);
