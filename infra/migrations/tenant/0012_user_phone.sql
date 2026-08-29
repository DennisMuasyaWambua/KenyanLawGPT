-- Staff phone numbers for WhatsApp/SMS calendar reminders (previously only
-- clients had a phone on file). Idempotent so `make migrate` reaches existing firms.
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone text NOT NULL DEFAULT '';
