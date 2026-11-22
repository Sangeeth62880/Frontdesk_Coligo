CREATE TABLE request_idempotency (
    actor text NOT NULL,
    key text NOT NULL,
    fingerprint text NOT NULL,
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(actor, key)
);
