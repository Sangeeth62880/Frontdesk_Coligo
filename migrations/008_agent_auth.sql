-- Email already exists and is unique. Give the nine seeded agents real addresses.
UPDATE agents SET email = lower(name) || '@arvo.example'
WHERE email = 'agent' || id || '@arvo.example';
UPDATE agents SET email = lower(email);
ALTER TABLE agents ADD CONSTRAINT agents_email_lowercase CHECK (email = lower(email));
ALTER TABLE agents ADD COLUMN password_hash text;
ALTER TABLE agents ADD COLUMN is_active boolean NOT NULL DEFAULT true;
CREATE TABLE agent_sessions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id bigint NOT NULL REFERENCES agents(id),
    token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE TABLE agent_login_attempts (
    email text PRIMARY KEY CHECK (email = lower(email)),
    failures integer NOT NULL DEFAULT 0,
    window_start timestamptz NOT NULL,
    locked_until timestamptz
);
