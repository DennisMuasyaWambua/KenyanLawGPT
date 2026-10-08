package africastalking

import "testing"

func TestNormalizePhone(t *testing.T) {
	cases := map[string]string{
		"0712345678":        "+254712345678",
		"0112345678":        "+254112345678",
		"712345678":         "+254712345678",
		"254712345678":      "+254712345678",
		"+254 712 345 678":  "+254712345678",
		"+1 (415) 555-0100": "+14155550100",
		"":                  "",
		"n/a":               "",
	}
	for in, want := range cases {
		if got := NormalizePhone(in); got != want {
			t.Errorf("NormalizePhone(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestATSuccess(t *testing.T) {
	for _, code := range []int{100, 101, 102} {
		if !atSuccess(code) {
			t.Errorf("code %d should be success", code)
		}
	}
	for _, code := range []int{0, 401, 402, 403, 500} {
		if atSuccess(code) {
			t.Errorf("code %d should be failure", code)
		}
	}
}
