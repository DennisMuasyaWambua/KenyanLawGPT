package handlers

import (
	"testing"

	"github.com/wakiliai/gateway/internal/repository"
)

func TestNormalizeScope(t *testing.T) {
	cases := map[string]struct {
		want string
		ok   bool
	}{
		"":         {"personal", true},
		"personal": {"personal", true},
		"shared":   {"firm", true},
		"firm":     {"firm", true},
		"admin":    {"", false},
	}
	for in, exp := range cases {
		got, ok := normalizeScope(in)
		if got != exp.want || ok != exp.ok {
			t.Errorf("normalizeScope(%q) = (%q,%v), want (%q,%v)", in, got, ok, exp.want, exp.ok)
		}
	}
}

func TestValidateReminders(t *testing.T) {
	if msg := validateReminders([]reminderInput{{OffsetMinutes: 1440}, {OffsetMinutes: 60, Channel: "email"}}); msg != "" {
		t.Errorf("valid reminders rejected: %s", msg)
	}
	if validateReminders([]reminderInput{{OffsetMinutes: -5}}) == "" {
		t.Error("negative offset should be rejected")
	}
	if validateReminders([]reminderInput{{Channel: "carrier-pigeon"}}) == "" {
		t.Error("unknown channel should be rejected")
	}
}

// The core privacy guarantee: a personal event is mutable only by its owner —
// never by another user, and no permission (sharedAllowed) can override that.
func TestMayMutateEvent(t *testing.T) {
	s := &Server{}
	personal := &repository.CalendarEvent{Scope: "personal", OwnerID: "owner-1"}
	shared := &repository.CalendarEvent{Scope: "firm", OwnerID: "owner-1"}

	if !s.mayMutateEvent(nil, personal, "owner-1", false) {
		t.Error("owner must be able to mutate their own personal event")
	}
	if s.mayMutateEvent(nil, personal, "someone-else", true) {
		t.Error("a non-owner must NOT mutate a personal event even with shared permission")
	}
	if s.mayMutateEvent(nil, shared, "someone-else", false) {
		t.Error("shared event must require the shared permission")
	}
	if !s.mayMutateEvent(nil, shared, "someone-else", true) {
		t.Error("shared event should be mutable with the shared permission")
	}
}
