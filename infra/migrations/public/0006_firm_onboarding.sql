-- Self-service firm signup: the owner is walked through an onboarding wizard
-- (roles & permissions, team invites) until they finish or skip it. Existing
-- firms predate the wizard and are marked done so they never see it.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_completed_at timestamptz;
UPDATE tenants SET onboarding_completed_at = created_at WHERE onboarding_completed_at IS NULL;
-- Contact details captured at signup.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS phone text NOT NULL DEFAULT '';
