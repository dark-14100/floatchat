-- =============================================================================
-- FloatChat — Create Read-Only Database User
--
-- Creates the floatchat_readonly PostgreSQL user with SELECT-only privileges
-- on all tables and materialized views in the public schema.
--
-- Idempotent: safe to run multiple times.
--
-- Usage:
--   psql -U floatchat -d floatchat -f scripts/create_readonly_user.sql
-- =============================================================================

-- Create the role if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'floatchat_readonly'
    ) THEN
        CREATE ROLE floatchat_readonly WITH LOGIN PASSWORD 'floatchat_readonly';
        RAISE NOTICE 'Created role floatchat_readonly';
    ELSE
        RAISE NOTICE 'Role floatchat_readonly already exists — skipping creation';
    END IF;
END
$$;

-- Grant USAGE on the public schema
GRANT USAGE ON SCHEMA public TO floatchat_readonly;

-- Grant SELECT on all existing tables (includes materialized views)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO floatchat_readonly;

-- Ensure future tables are also readable (for new migrations)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO floatchat_readonly;
