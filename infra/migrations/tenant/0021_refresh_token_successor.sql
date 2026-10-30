-- A rotated refresh token remembers the token that replaced it. When a phone
-- locks (or drops off the network) mid-refresh, the server has already rotated
-- the token but the device never receives the new one; it then presents the
-- old token again on wake. Knowing the successor — and that it was never used —
-- lets the gateway renew that session instead of signing the user out
-- (repository.ConsumeRefreshToken).
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS replaced_by uuid;
