-- Platform (super-admin) control plane. These accounts operate ACROSS all
-- tenants from the public schema — deliberately outside the per-tenant schema
-- isolation firm users are bound to. Kept separate from the tenant `users`
-- table so the two identity domains never mix.

CREATE TABLE IF NOT EXISTS platform_admins (
    id            uuid PRIMARY KEY,
    email         text NOT NULL,
    full_name     text NOT NULL DEFAULT '',
    password_hash text NOT NULL,
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS platform_admins_email_unique ON platform_admins (lower(email));

-- Rotating refresh tokens for admin sessions (mirrors the tenant scheme; only a
-- SHA-256 hash is persisted).
CREATE TABLE IF NOT EXISTS platform_admin_refresh_tokens (
    id         uuid PRIMARY KEY,
    admin_id   uuid NOT NULL REFERENCES platform_admins(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Accountability trail for every mutating super-admin action (who did what to
-- which firm). Separate from the per-tenant audit_log.
CREATE TABLE IF NOT EXISTS platform_audit (
    id               uuid PRIMARY KEY,
    admin_id         uuid,
    admin_email      text NOT NULL DEFAULT '',
    action           text NOT NULL,
    target_tenant_id uuid,
    detail           jsonb NOT NULL DEFAULT '{}',
    ip               text NOT NULL DEFAULT '',
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS platform_audit_time ON platform_audit (created_at DESC);

-- Let a platform admin read the cross-tenant audit_log. RLS policies are
-- permissive (OR-combined), so this adds a bypass keyed on a transaction-scoped
-- GUC that only the admin DB path (db.WithPlatformAdmin) ever sets.
DROP POLICY IF EXISTS audit_platform_admin ON audit_log;
CREATE POLICY audit_platform_admin ON audit_log
    USING (current_setting('app.platform_admin', true) = 'true');

GRANT SELECT, INSERT, UPDATE, DELETE ON platform_admins, platform_admin_refresh_tokens, platform_audit TO wakili_app;
