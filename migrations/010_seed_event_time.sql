-- Supplied event time is trusted only for an explicitly enabled owner seed.
-- SECURITY INVOKER is intentional: runtime cannot impersonate the table owner.
CREATE OR REPLACE FUNCTION stamp_event() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
    IF pg_catalog.current_setting('frontdesk.seeding', true) = 'on'
       AND current_user = pg_catalog.pg_get_userbyid(
           (SELECT relowner FROM pg_catalog.pg_class WHERE oid = TG_RELID)) THEN
        RETURN NEW;
    END IF;
    NEW.created_at := pg_catalog.clock_timestamp();
    RETURN NEW;
END;
$$;
