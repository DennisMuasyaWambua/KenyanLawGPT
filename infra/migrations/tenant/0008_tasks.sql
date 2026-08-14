-- Task assignment against matters. "Manager" is not a role — task management is
-- gated purely on the tasks.* permissions (assigned in the RBAC catalog).

CREATE TABLE IF NOT EXISTS tasks (
    id           uuid PRIMARY KEY,
    matter_id    uuid NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
    assigned_to  uuid REFERENCES users(id) ON DELETE SET NULL,
    assigned_by  uuid NOT NULL,
    title        text NOT NULL,
    description  text NOT NULL DEFAULT '',
    due_date     timestamptz,
    status       text NOT NULL DEFAULT 'todo'   CHECK (status IN ('todo','in_progress','blocked','done')),
    priority     text NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS tasks_assignee ON tasks (assigned_to, status);
CREATE INDEX IF NOT EXISTS tasks_matter   ON tasks (matter_id);

-- Grants: full task management to the Owner and to managers (anyone who can
-- already see all firm matters); own-task visibility to anyone who sees their
-- own matters.
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r
CROSS JOIN (VALUES ('tasks.create'), ('tasks.assign'), ('tasks.view_own'), ('tasks.view_all')) AS p(perm)
WHERE r.is_protected = true
   OR EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission = 'matters.view_all')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission)
SELECT r.id, 'tasks.view_own'
FROM roles r
WHERE EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission = 'matters.view_own')
ON CONFLICT DO NOTHING;
