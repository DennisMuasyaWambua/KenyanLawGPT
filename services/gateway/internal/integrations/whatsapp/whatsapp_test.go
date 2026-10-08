package whatsapp

import "testing"

func TestTemplateParam(t *testing.T) {
	cases := map[string]string{
		"Reminder: hearing at 09:00":            "Reminder: hearing at 09:00",
		"Update on KE/1:\nFiled\r\n\nnext step": "Update on KE/1: · Filed · next step",
		"a\tb      c":                          "a b c",
	}
	for in, want := range cases {
		if got := templateParam(in); got != want {
			t.Errorf("templateParam(%q) = %q, want %q", in, got, want)
		}
	}
}
