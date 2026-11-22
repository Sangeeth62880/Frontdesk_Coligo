ALTER TABLE tickets ADD COLUMN first_reply_required boolean NOT NULL DEFAULT true;
ALTER TABLE tickets ADD COLUMN first_reply_due_at timestamptz;
ALTER TABLE tickets ADD COLUMN first_reply_breached boolean NOT NULL DEFAULT false;
ALTER TABLE tickets ADD COLUMN resolution_breached boolean NOT NULL DEFAULT false;
ALTER TABLE tickets ADD COLUMN version integer NOT NULL DEFAULT 0;
CREATE FUNCTION ticket_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ticket_version BEFORE UPDATE OF status, assignee_id, priority ON tickets
FOR EACH ROW EXECUTE FUNCTION ticket_version();
ALTER TABLE events DROP CONSTRAINT events_event_type_check;
ALTER TABLE events ADD CHECK (event_type IN ('created','claimed','reassigned','public_reply','internal_note_added','status_changed','priority_changed','paused','resumed','auto_closed','reopened','linked_ticket_created'));

-- Import already recorded completed-cycle breaches without rewriting audit history.
UPDATE tickets t SET resolution_breached = true
WHERE EXISTS (SELECT 1 FROM resolution_cycles c WHERE c.ticket_id=t.id AND c.breached);
-- A recorded agent creation is an on-behalf intake; unknown legacy sources
-- keep the conservative default rather than silently removing an obligation.
UPDATE tickets t SET first_reply_required = false
WHERE EXISTS (SELECT 1 FROM events e WHERE e.ticket_id=t.id
              AND e.event_type='created' AND e.actor LIKE 'agent:%');
