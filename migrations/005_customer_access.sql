ALTER TABLE tickets ADD COLUMN customer_token uuid NOT NULL DEFAULT gen_random_uuid();
CREATE INDEX tickets_customer_token ON tickets(customer_token);
