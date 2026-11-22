CREATE TABLE customer_intake_limits (
    client_hash text NOT NULL PRIMARY KEY,
    window_start timestamptz NOT NULL,
    attempts integer NOT NULL CHECK (attempts >= 1)
);
