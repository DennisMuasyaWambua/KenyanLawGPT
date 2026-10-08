// Package localtime renders instants in East Africa Time for user-facing text
// (reminders, notifications). Timestamps come back from Postgres in the server
// process's zone — UTC in a container — so formatting them directly tells a
// Nairobi advocate their 12:00 hearing is at 09:00.
package localtime

import (
	"time"
	_ "time/tzdata" // the alpine runtime image ships no zoneinfo
)

// EAT is Africa/Nairobi; Kenya observes no DST so a fixed UTC+3 zone is an exact
// fallback if the tz database is somehow unavailable.
var EAT = func() *time.Location {
	if loc, err := time.LoadLocation("Africa/Nairobi"); err == nil {
		return loc
	}
	return time.FixedZone("EAT", 3*60*60)
}()

// Layout is the human format used in reminder messages: "Mon 02 Jan 2006 15:04".
const Layout = "Mon 02 Jan 2006 15:04"

// Format renders t in East Africa Time using layout (Layout when empty).
func Format(t time.Time, layout string) string {
	if layout == "" {
		layout = Layout
	}
	return t.In(EAT).Format(layout)
}
