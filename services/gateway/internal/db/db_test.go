package db

import "testing"

// Schema-name validation is the choke point that keeps attacker-controlled
// strings out of SET search_path. Everything not shaped exactly like a
// provisioned tenant schema must be rejected.
func TestValidSchemaName(t *testing.T) {
	valid := []string{
		"tenant_0123456789abcdef0123456789abcdef",
		"tenant_ffffffffffffffffffffffffffffffff",
	}
	for _, s := range valid {
		if !ValidSchemaName(s) {
			t.Errorf("expected valid: %s", s)
		}
	}
	invalid := []string{
		"",
		"public",
		"tenant_",
		"tenant_123",                                  // too short
		"tenant_0123456789abcdef0123456789abcdeff",   // too long
		"tenant_0123456789ABCDEF0123456789abcdef",    // uppercase
		"tenant_0123456789abcdef0123456789abcdeg",    // non-hex
		"tenant_0123456789abcdef0123456789abcde;",    // injection
		`tenant_0123456789abcdef0123456789abcde"`,    // quote
		"tenant_0123456789abcdef0123456789abcdef, public", // path smuggling
		"other_0123456789abcdef0123456789abcdef",
	}
	for _, s := range invalid {
		if ValidSchemaName(s) {
			t.Errorf("expected invalid: %q", s)
		}
	}
}
