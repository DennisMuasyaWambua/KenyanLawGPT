-- Firm-scoped RBAC: custom roles + a granular permission catalog, replacing the
-- hardcoded users.role enum. Roles live in the tenant schema, so they are
-- firm-scoped by construction (the schema IS the firm). The permission *catalog*
-- is defined in Go (internal/rbac); role_permissions stores the permission key as
-- text, validated in application code. This migration also bootstraps default
-- roles and backfills existing users/invites so the switch is seamless.

CREATE TABLE IF NOT EXISTS roles (
    id           uuid PRIMARY KEY,
    name         text NOT NULL,
    description  text NOT NULL DEFAULT '',
    is_protected boolean NOT NULL DEFAULT false,   -- true only for the auto-created "Owner"
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS roles_name_unique ON roles (lower(name));

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id    uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission text NOT NULL,
    PRIMARY KEY (role_id, permission)
);

-- One role per user (source of truth for authorization). users.role stays as a
-- denormalized display label. ON DELETE RESTRICT: a role with members can't be
-- deleted out from under them.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id uuid REFERENCES roles(id) ON DELETE RESTRICT;

-- Invites now carry a role_id (the pre-assigned role); role text kept as a label.
ALTER TABLE staff_invites ADD COLUMN IF NOT EXISTS role_id uuid REFERENCES roles(id) ON DELETE SET NULL;

-- ---------------------------------------------------------------------------
-- Seed the protected Owner role (always) with ALL catalog permissions.
-- ---------------------------------------------------------------------------
INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Owner', 'Full access to the firm workspace', true
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'owner');

INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm
FROM roles r,
     (VALUES
        ('matters.create'),('matters.view_own'),('matters.view_all'),('matters.edit'),('matters.delete'),
        ('documents.upload'),('documents.view'),('documents.download'),('documents.delete'),
        ('research.query'),('research.reason'),
        ('drafting.create'),
        ('clients.view'),('clients.manage'),
        ('billing.view'),('billing.manage'),
        ('calendar.view_shared'),('calendar.create_shared'),('calendar.edit_shared'),('calendar.delete_shared'),
        ('comms.view'),('comms.send'),
        ('users.invite'),('users.manage_roles'),('users.remove'),('users.view'),
        ('roles.manage'),
        ('firm_settings.edit'),
        ('kdpa.view_audit'),('kdpa.export'),('kdpa.erase')
     ) AS c(perm)
WHERE lower(r.name) = 'owner'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Existing tenants only: recreate the legacy staff roles actually in use so no
-- current user is orphaned. Fresh firms have only the owner, so only Owner is
-- created here; the other templates are offered via the API during onboarding.
-- ---------------------------------------------------------------------------
INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Partner', 'Senior advocate — firm management', false
WHERE EXISTS (SELECT 1 FROM users WHERE role = 'partner')
  AND NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'partner');

INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm
FROM roles r,
     (VALUES
        ('matters.create'),('matters.view_own'),('matters.view_all'),('matters.edit'),('matters.delete'),
        ('documents.upload'),('documents.view'),('documents.download'),('documents.delete'),
        ('research.query'),('research.reason'),('drafting.create'),
        ('clients.view'),('clients.manage'),('billing.view'),('billing.manage'),
        ('calendar.view_shared'),('calendar.create_shared'),('calendar.edit_shared'),('calendar.delete_shared'),
        ('comms.view'),('comms.send'),
        ('users.invite'),('users.view'),('roles.manage'),('kdpa.view_audit')
     ) AS c(perm)
WHERE lower(r.name) = 'partner'
ON CONFLICT DO NOTHING;

INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Associate', 'Advocate handling files', false
WHERE EXISTS (SELECT 1 FROM users WHERE role = 'associate')
  AND NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'associate');

INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm
FROM roles r,
     (VALUES
        ('matters.create'),('matters.view_all'),('matters.edit'),
        ('documents.upload'),('documents.view'),('documents.download'),
        ('research.query'),('research.reason'),('drafting.create'),
        ('clients.view'),
        ('calendar.view_shared'),('calendar.create_shared'),('calendar.edit_shared'),
        ('comms.view'),('comms.send')
     ) AS c(perm)
WHERE lower(r.name) = 'associate'
ON CONFLICT DO NOTHING;

INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Paralegal', 'Support staff — limited access', false
WHERE EXISTS (SELECT 1 FROM users WHERE role = 'paralegal')
  AND NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'paralegal');

INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm
FROM roles r,
     (VALUES
        ('matters.view_own'),
        ('documents.upload'),('documents.view'),
        ('research.query'),
        ('calendar.view_shared'),
        ('comms.view')
     ) AS c(perm)
WHERE lower(r.name) = 'paralegal'
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Backfill role_id from the legacy role string. Portal clients keep role_id NULL
-- (they are not firm members and use the client portal).
-- ---------------------------------------------------------------------------
UPDATE users u SET role_id = r.id
FROM roles r
WHERE u.role_id IS NULL AND u.role <> 'client' AND lower(r.name) = u.role;

UPDATE staff_invites si SET role_id = r.id
FROM roles r
WHERE si.role_id IS NULL AND lower(r.name) = si.role;

-- Drop the old CHECK enums so role/label can be any custom role name.
ALTER TABLE users         DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE staff_invites DROP CONSTRAINT IF EXISTS staff_invites_role_check;
