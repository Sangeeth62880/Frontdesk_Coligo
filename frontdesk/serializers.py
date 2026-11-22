"""Explicit customer-facing field lists: no arbitrary DB dictionaries escape."""
import csv
import io
from collections.abc import Mapping, Iterable

TICKET_FIELDS = (
    "id", "subject", "priority", "status", "created_at", "start_at",
    "first_replied_at", "resolved_at", "closed_at", "previous_ticket_id",
)
# Every ticket model column must be explicitly classified by the schema contract test.
PRIVATE_TICKET_FIELDS = {
    "customer_email", "assignee_id", "customer_token", "first_reply_required",
    "first_reply_due_at", "first_reply_breached", "resolution_breached", "version",
}
MESSAGE_FIELDS = ("id", "author_type", "body", "created_at")
CSV_FIELDS = ("id", "subject", "priority", "status", "created_at", "previous_ticket_id")


def customer_ticket(ticket: Mapping, messages: Iterable[Mapping] = ()) -> dict:
    result = {field: ticket[field] for field in TICKET_FIELDS}
    result["messages"] = [{field: message[field] for field in MESSAGE_FIELDS} for message in messages]
    return result


def customer_csv(tickets: Iterable[Mapping]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for ticket in tickets:
        # Neutralize spreadsheet formulas in user-controlled text fields.
        row = {field: ticket[field] for field in CSV_FIELDS}
        for key, value in row.items():
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                row[key] = "'" + value
        writer.writerow(row)
    return output.getvalue()
