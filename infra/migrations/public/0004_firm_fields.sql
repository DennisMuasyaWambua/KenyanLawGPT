-- Firm (tenant) registration + owner pointer. The tenant row already models
-- the "Firm" (id, name, plan=subscription tier, created_at); we add the LSK /
-- firm registration number and a pointer to the owner user. owner_user_id is a
-- uuid into the tenant schema's users table — deliberately NOT a cross-schema
-- FK (users live per-tenant), so it is validated in application code.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS reg_number    text NOT NULL DEFAULT '';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS owner_user_id uuid;
