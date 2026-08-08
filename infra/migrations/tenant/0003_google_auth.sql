-- Google sign-in / sign-up and email-based staff invites.
--
-- Users may now authenticate with Google instead of a local password, so
-- password_hash becomes optional; google_sub links a user to a verified Google
-- account (unique within the tenant). auth_provider records how the account
-- was created ('password' | 'google').
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider text NOT NULL DEFAULT 'password'
    CHECK (auth_provider IN ('password', 'google'));
CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_unique ON users (google_sub)
    WHERE google_sub IS NOT NULL;

-- Staff invites: an owner/partner invites a colleague by email; the invitee
-- accepts via a tokenised link and sets a password (or links Google). Only the
-- SHA-256 hash of the token is stored, mirroring refresh_tokens.
CREATE TABLE IF NOT EXISTS staff_invites (
    id         uuid PRIMARY KEY,
    email      text NOT NULL,
    full_name  text NOT NULL DEFAULT '',
    role       text NOT NULL CHECK (role IN ('owner','partner','associate','paralegal','client')),
    token_hash text NOT NULL UNIQUE,
    invited_by uuid REFERENCES users(id) ON DELETE SET NULL,
    status     text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','revoked')),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz
);
CREATE INDEX IF NOT EXISTS staff_invites_email ON staff_invites (lower(email));
