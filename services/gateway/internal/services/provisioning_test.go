package services

import (
	"regexp"
	"strings"
	"testing"
)

// deriveSlug backs solo (individual) sign-up, where no firm slug is supplied.
// The result must always be a valid tenant slug: 3-40 chars, lowercase
// letters/digits/hyphens only (the same rule ProvisionTenant enforces).
var validSlug = regexp.MustCompile(`^[a-z0-9-]{3,40}$`)

func TestDeriveSlug(t *testing.T) {
	cases := []struct {
		name       string
		wantPrefix string
	}{
		{"Mwangi & Advocates", "mwangi-advocates-"},
		{"Jane", "jane-"},
		{"  A ", "firm-"}, // too short after sanitising -> "firm"
		{"", "firm-"},
		{"Otieno, Kamau & Co. Advocates LLP (Nairobi)", "otieno-kamau-co-advocates-llp-"},
	}
	for _, tc := range cases {
		got := deriveSlug(tc.name)
		if !validSlug.MatchString(got) {
			t.Errorf("deriveSlug(%q) = %q is not a valid slug", tc.name, got)
		}
		if !strings.HasPrefix(got, tc.wantPrefix) {
			t.Errorf("deriveSlug(%q) = %q, want prefix %q", tc.name, got, tc.wantPrefix)
		}
	}
}

func TestDeriveSlugUnique(t *testing.T) {
	// The random suffix keeps concurrent solo signups from colliding.
	if deriveSlug("Jane") == deriveSlug("Jane") {
		t.Error("expected distinct slugs for repeated derivation")
	}
}
