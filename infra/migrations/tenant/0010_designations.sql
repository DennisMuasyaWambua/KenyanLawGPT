-- Firm designations replace the generic role set. The protected top role
-- (formerly "Owner") becomes "Managing Partner"; five more designations are
-- seeded with permission sets that drive nav visibility + the per-designation
-- dashboard. Idempotent so `make migrate` brings existing tenants in line too.
--
-- Gating rules baked into the permission sets:
--   * Clients: Secretary + Partner + Managing Partner only
--   * Tasks / Billing: Partner + Managing Partner only
--   * User onboarding (users.invite/manage_roles/remove, roles.manage): Managing Partner only
--   * Partner: every feature button; Managing Partner: everything incl. onboarding

-- Protected role rename (keeps its full permission set + is_protected flag).
UPDATE roles SET name = 'Managing Partner',
       description = 'Managing partner — full firm control and staff onboarding'
WHERE lower(name) = 'owner';
UPDATE users         SET role = 'Managing Partner' WHERE role = 'Owner';
UPDATE staff_invites SET role = 'Managing Partner' WHERE role = 'Owner';

-- Helper pattern per designation: create the role if missing, then grant perms.
INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Partner', 'Advocate partner — full feature access', false
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'partner');
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm FROM roles r,
 (VALUES
   ('matters.create'),('matters.view_own'),('matters.view_all'),('matters.edit'),('matters.delete'),
   ('documents.upload'),('documents.view'),('documents.download'),('documents.delete'),
   ('research.query'),('research.reason'),('drafting.create'),
   ('clients.view'),('clients.create'),('clients.edit'),('clients.advance_stage'),('clients.manage'),
   ('tasks.create'),('tasks.assign'),('tasks.view_own'),('tasks.view_all'),
   ('recordings.create'),('recordings.view_own'),('recordings.view_all'),
   ('billing.view'),('billing.manage'),
   ('calendar.view_shared'),('calendar.create_shared'),('calendar.edit_shared'),('calendar.delete_shared'),
   ('comms.view'),('comms.send'),('users.view')
 ) AS c(perm)
WHERE lower(r.name) = 'partner' ON CONFLICT DO NOTHING;

INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Associate', 'Advocate handling files & research', false
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'associate');
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm FROM roles r,
 (VALUES
   ('matters.create'),('matters.view_own'),('matters.view_all'),('matters.edit'),
   ('documents.upload'),('documents.view'),('documents.download'),
   ('research.query'),('research.reason'),('drafting.create'),
   ('recordings.create'),('recordings.view_own'),
   ('calendar.view_shared'),('calendar.create_shared'),('calendar.edit_shared'),
   ('comms.view'),('comms.send')
 ) AS c(perm)
WHERE lower(r.name) = 'associate' ON CONFLICT DO NOTHING;

INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Secretary', 'Firm secretary — files, clients & scheduling', false
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'secretary');
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm FROM roles r,
 (VALUES
   ('matters.view_own'),('matters.view_all'),('matters.create'),('matters.edit'),
   ('documents.upload'),('documents.view'),('documents.download'),
   ('clients.view'),('clients.create'),('clients.edit'),('clients.advance_stage'),('clients.manage'),
   ('calendar.view_shared'),('calendar.create_shared'),('calendar.edit_shared'),
   ('comms.view'),('comms.send')
 ) AS c(perm)
WHERE lower(r.name) = 'secretary' ON CONFLICT DO NOTHING;

INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Clerk', 'Court/office clerk — files & scheduling', false
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'clerk');
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm FROM roles r,
 (VALUES
   ('matters.view_own'),('matters.view_all'),('matters.create'),('matters.edit'),
   ('documents.upload'),('documents.view'),('documents.download'),
   ('recordings.create'),('recordings.view_own'),
   ('calendar.view_shared'),('calendar.create_shared'),
   ('comms.view')
 ) AS c(perm)
WHERE lower(r.name) = 'clerk' ON CONFLICT DO NOTHING;

INSERT INTO roles (id, name, description, is_protected)
SELECT gen_random_uuid(), 'Intern', 'Pupil/intern — read-mostly access', false
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'intern');
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm FROM roles r,
 (VALUES
   ('matters.view_own'),('matters.view_all'),
   ('documents.view'),('documents.download'),
   ('calendar.view_shared'),
   ('comms.view')
 ) AS c(perm)
WHERE lower(r.name) = 'intern' ON CONFLICT DO NOTHING;
