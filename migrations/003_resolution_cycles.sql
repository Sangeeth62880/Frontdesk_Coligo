-- Original tickets.start_at and first-reply history are never reset on reopen.
CREATE TABLE resolution_cycles (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id bigint NOT NULL REFERENCES tickets(id),
    cycle_number integer NOT NULL CHECK (cycle_number > 0),
    opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    start_at timestamptz NOT NULL,
    ended_at timestamptz,
    resolution_due_at timestamptz,
    breached boolean,
    UNIQUE(ticket_id, cycle_number),
    CHECK (ended_at IS NULL OR ended_at >= opened_at)
);
CREATE UNIQUE INDEX one_active_resolution_cycle ON resolution_cycles(ticket_id) WHERE ended_at IS NULL;
INSERT INTO resolution_cycles(ticket_id, cycle_number, opened_at, start_at, ended_at)
SELECT id, 1, created_at, start_at, COALESCE(resolved_at, closed_at) FROM tickets;
ALTER TABLE ticket_pauses ADD COLUMN cycle_id bigint REFERENCES resolution_cycles(id);
UPDATE ticket_pauses p SET cycle_id = c.id FROM resolution_cycles c WHERE c.ticket_id = p.ticket_id;
ALTER TABLE ticket_pauses ALTER COLUMN cycle_id SET NOT NULL;
