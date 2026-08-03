-- Runs once at cluster creation (docker-entrypoint-initdb.d), as superuser,
-- against POSTGRES_DB=wakili.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Application role: NOT a superuser, so row-level security on shared tables
-- (public.audit_log) actually binds. It may create tenant schemas (owned by
-- itself) during provisioning.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wakili_app') THEN
    CREATE ROLE wakili_app LOGIN PASSWORD 'wakili_app_pw';
  END IF;
END $$;

GRANT CONNECT ON DATABASE wakili TO wakili_app;
GRANT CREATE  ON DATABASE wakili TO wakili_app;
GRANT USAGE   ON SCHEMA public TO wakili_app;
