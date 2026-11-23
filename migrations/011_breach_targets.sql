-- Preserve the deadline that first breached, independently of later re-triage.
ALTER TABLE tickets ADD COLUMN first_reply_breach_due_at timestamptz;
ALTER TABLE resolution_cycles ADD COLUMN breach_due_at timestamptz;
UPDATE resolution_cycles SET breach_due_at=resolution_due_at
WHERE breached AND resolution_due_at IS NOT NULL;
