-- Client onboarding pipeline: intake -> engaged -> active matter, with an
-- auditable stage-change trail (POCAMLA/AML). Extends the existing clients table
-- (which had no lifecycle) and widens matters.status with 'on_hold'.

ALTER TABLE clients ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'lead'
    CHECK (status IN ('lead','intake','conflict_check','engaged','active','closed'));
ALTER TABLE clients ADD COLUMN IF NOT EXISTS client_type text NOT NULL DEFAULT 'individual'
    CHECK (client_type IN ('individual','company'));
ALTER TABLE clients ADD COLUMN IF NOT EXISTS company_reg_number text NOT NULL DEFAULT ''; -- national_id reuses id_number
ALTER TABLE clients ADD COLUMN IF NOT EXISTS conflict_check_at timestamptz;               -- manual gate
ALTER TABLE clients ADD COLUMN IF NOT EXISTS conflict_check_by uuid;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS retainer_ref text NOT NULL DEFAULT '';        -- signed engagement/retainer
ALTER TABLE clients ADD COLUMN IF NOT EXISTS kyc_completed_at timestamptz;                 -- POCAMLA KYC/AML
ALTER TABLE clients ADD COLUMN IF NOT EXISTS kyc_ref text NOT NULL DEFAULT '';

-- Auditable pipeline history: who moved a client between stages and when.
CREATE TABLE IF NOT EXISTS client_stage_events (
    id          uuid PRIMARY KEY,
    client_id   uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    from_status text NOT NULL,
    to_status   text NOT NULL,
    note        text NOT NULL DEFAULT '',
    advanced_by uuid NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS client_stage_events_client ON client_stage_events (client_id, created_at);

-- Widen matter status with 'on_hold' (keep the richer litigation lifecycle).
ALTER TABLE matters DROP CONSTRAINT IF EXISTS matters_status_check;
ALTER TABLE matters ADD CONSTRAINT matters_status_check
    CHECK (status IN ('intake','active','awaiting_court','appeal','closed','on_hold'));

-- Grant the new pipeline permissions to the protected Owner role (so live owners
-- keep full access) and to any role that already manages clients today.
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r
CROSS JOIN (VALUES ('clients.create'), ('clients.edit'), ('clients.advance_stage')) AS p(perm)
WHERE r.is_protected = true
   OR EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission = 'clients.manage')
ON CONFLICT DO NOTHING;
