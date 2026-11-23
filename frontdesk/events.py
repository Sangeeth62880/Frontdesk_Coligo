"""Audit writes deliberately accept no message or internal note body."""
import json

from psycopg.types.json import Jsonb

# Each event permits only its defined metadata keys, never arbitrary request data.
PAYLOAD_FIELDS = {
    'created': {'message_id', 'source', 'priority', 'cycle_number', 'previous_ticket_id', 'resolution_due_at'},
    'claimed': {'assignee_id'},
    'reassigned': {'assignee_id'},
    'linked_ticket_created': {'previous_ticket_id'},
    'public_reply': {'message_id', 'first_replied_at'},
    'internal_note_added': {'note_id'},
    'status_changed': {'status', 'cycle_number', 'resolution_due_at', 'breached'},
    'priority_changed': {'priority', 'first_reply_due_at', 'resolution_due_at', 'cycle_number'},
    'paused': {'pause_id', 'cycle_number'},
    'resumed': {'pause_id', 'cycle_number'},
    'auto_closed': {'status', 'cycle_number', 'resolution_due_at', 'breached'},
    'reopened': {'status', 'cycle_number', 'start_at', 'resolution_due_at'},
}


def log_event(db, ticket_id, actor, event_type, before=None, after=None):
    allowed = PAYLOAD_FIELDS[event_type]
    def payload(value):
        if value is None:
            return None
        if not value.keys() <= allowed:
            raise ValueError(f"Unexpected audit metadata for {event_type}")
        return Jsonb(json.loads(json.dumps(value, default=lambda item: item.isoformat())))
    db.execute(
        "INSERT INTO events(ticket_id, actor, event_type, before_value, after_value) VALUES (%s, %s, %s, %s, %s)",
        (ticket_id, actor, event_type, payload(before), payload(after)),
    )
