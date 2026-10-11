package services

import (
	"strings"
	"testing"
)

// deriveSlug backs solo (individual) sign-up, where no firm slug is supplied.
// The result must always pass validSlug, the rule ProvisionTenant enforces.

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

func TestSlugFromName(t *testing.T) {
	cases := map[string]string{
		"Mwangi & Co. Advocates":    "mwangi-co-advocates",
		"  Otieno, Kamau LLP ":      "otieno-kamau-llp",
		"C. Karwitha C.K Advocates": "c-karwitha-c-k-advocates",
	}
	for in, want := range cases {
		if got := SlugFromName(in); got != want || !validSlug.MatchString(got) {
			t.Errorf("SlugFromName(%q) = %q, want %q", in, got, want)
		}
	}
	long := SlugFromName(strings.Repeat("abcdefghi ", 10))
	if !validSlug.MatchString(long) {
		t.Errorf("long name gave invalid slug %q", long)
	}
}

func TestValidSlugRejectsUnsafeCharacters(t *testing.T) {
	for _, bad := range []string{"a&b", "firm!", "-lead", "trail-", "ab", "Upper", "a.b", "a b"} {
		if validSlug.MatchString(bad) {
			t.Errorf("validSlug accepted %q", bad)
		}
	}
	if !validSlug.MatchString("mwangi-advocates") {
		t.Error("validSlug rejected a normal slug")
	}
}
