-- Partners (not only the Managing Partner) can onboard and manage staff:
-- create/invite accounts, view members, assign designations, and load the
-- designation list (roles.manage gates GET /roles used by the onboarding form).
-- Idempotent so `make migrate` applies it to existing firms too.
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, c.perm FROM roles r,
 (VALUES
   ('users.invite'),('users.view'),('users.manage_roles'),('users.remove'),('roles.manage')
 ) AS c(perm)
WHERE lower(r.name) = 'partner' ON CONFLICT DO NOTHING;
