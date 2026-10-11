-- Staff added by a firm admin receive an emailed temporary password. They must
-- replace it on first sign-in (enforced by the gateway on every request), and an
-- unused temporary password stops working after temp_password_expires_at.
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS temp_password_expires_at timestamptz;
