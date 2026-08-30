package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
)

// parseTime accepts RFC3339; falls back to a date (YYYY-MM-DD).
func parseTime(s string) (time.Time, bool) {
	if s == "" {
		return time.Time{}, false
	}
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t, true
	}
	if t, err := time.Parse("2006-01-02", s); err == nil {
		return t, true
	}
	return time.Time{}, false
}

// reminderInput is a reminder offset (minutes before start_time) and channel.
// Offsets (not absolute times) so rescheduling the event recomputes them.
type reminderInput struct {
	OffsetMinutes int    `json:"offset_minutes"`
	Channel       string `json:"channel"`
}

type eventInput struct {
	Scope       string          `json:"scope"` // "shared" (alias for "firm") | "personal"
	Title       string          `json:"title" binding:"required"`
	Description string          `json:"description"`
	Location    string          `json:"location"`
	FileID    *string         `json:"file_id"`
	StartAt     time.Time       `json:"start_at" binding:"required"`
	EndAt       *time.Time      `json:"end_at"`
	AllDay      bool            `json:"all_day"`
	Reminders   []reminderInput `json:"reminders"`
	// Staff invited to the event; calendar reminders fan out to them too.
	AttendeeUserIDs []string `json:"attendee_user_ids"`
}

// normalizeScope maps the API's "shared" onto the stored "firm" and defaults to
// "personal". Anything else is invalid.
func normalizeScope(s string) (string, bool) {
	switch s {
	case "", "personal":
		return "personal", true
	case "shared", "firm":
		return "firm", true
	default:
		return "", false
	}
}

// validateReminders checks channels/offsets before any DB work.
func validateReminders(in []reminderInput) string {
	for _, r := range in {
		if r.OffsetMinutes < 0 {
			return "reminder offset_minutes must be >= 0"
		}
		if r.Channel != "" && r.Channel != "email" && r.Channel != "sms" {
			return "reminder channel must be email or sms"
		}
	}
	return ""
}

// generateReminders materializes reminder rows from offsets relative to the
// event's start. Reminders whose time has already passed are skipped.
func generateReminders(ctx *gin.Context, tx pgx.Tx, eventID string, startAt time.Time, in []reminderInput) error {
	for _, r := range in {
		remindAt := startAt.Add(-time.Duration(r.OffsetMinutes) * time.Minute)
		if !remindAt.After(time.Now()) {
			continue
		}
		channel := r.Channel
		if channel == "" {
			channel = "email"
		}
		if err := repository.CreateReminder(ctx.Request.Context(), tx, &repository.EventReminder{
			ID: uuid.NewString(), EventID: eventID, RemindAt: remindAt, Channel: channel,
		}); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) ListCalendarEvents(c *gin.Context) {
	from, ok := parseTime(c.Query("from"))
	if !ok {
		from = time.Now().AddDate(0, 0, -7)
	}
	to, ok := parseTime(c.Query("to"))
	if !ok {
		to = time.Now().AddDate(0, 0, 60)
	}
	visibility := c.Query("visibility") // "", "all", "shared", "personal"
	includePersonal := visibility != "shared"
	includeShared := visibility != "personal" && s.can(c, rbac.PermCalendarViewShared)

	userID := s.claims(c).UserID()
	var events []repository.CalendarEvent
	var matters []repository.MatterCalendarItem
	if s.withTenant(c, func(tx pgx.Tx) error {
		e, err := repository.ListEvents(c.Request.Context(), tx, userID, from, to, includePersonal, includeShared)
		if err != nil {
			return err
		}
		events = e
		// Surface upcoming matters (court dates + deadlines) on the calendar.
		m, err := repository.ListMatterCalendar(c.Request.Context(), tx, from, to)
		matters = m
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"events": events, "matters": matters})
	}
}

func (s *Server) CreateCalendarEvent(c *gin.Context) {
	var in eventInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	scope, ok := normalizeScope(in.Scope)
	if !ok {
		badRequest(c, "scope must be 'shared' or 'personal'")
		return
	}
	if msg := validateReminders(in.Reminders); msg != "" {
		badRequest(c, msg)
		return
	}
	// Shared events require the create_shared permission; personal events are
	// always allowed for the owner.
	if scope == "firm" && !s.can(c, rbac.PermCalendarCreateShared) {
		c.JSON(http.StatusForbidden, gin.H{"error": "missing permission: " + rbac.PermCalendarCreateShared})
		return
	}
	userID := s.claims(c).UserID()
	e := &repository.CalendarEvent{
		ID: uuid.NewString(), Scope: scope, Title: in.Title, Description: in.Description,
		Location: in.Location, FileID: in.FileID, OwnerID: userID, StartAt: in.StartAt,
		EndAt: in.EndAt, AllDay: in.AllDay, CreatedBy: userID,
	}
	var reminders []repository.EventReminder
	if s.withTenant(c, func(tx pgx.Tx) error {
		if err := repository.CreateEvent(c.Request.Context(), tx, e); err != nil {
			return err
		}
		if err := generateReminders(c, tx, e.ID, e.StartAt, in.Reminders); err != nil {
			return err
		}
		if err := repository.SetEventAttendees(c.Request.Context(), tx, e.ID, in.AttendeeUserIDs); err != nil {
			return err
		}
		r, err := repository.RemindersForEvent(c.Request.Context(), tx, e.ID)
		reminders = r
		return err
	}) {
		e.AttendeeUserIDs = in.AttendeeUserIDs
		c.JSON(http.StatusCreated, gin.H{"event": e, "reminders": reminders})
	}
}

func (s *Server) UpdateCalendarEvent(c *gin.Context) {
	var in eventInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if msg := validateReminders(in.Reminders); msg != "" {
		badRequest(c, msg)
		return
	}
	userID := s.claims(c).UserID()
	canEditShared := s.can(c, rbac.PermCalendarEditShared) // precomputed (no nested tx)
	id := c.Param("id")

	var reminders []repository.EventReminder
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		existing, err := repository.GetEvent(c.Request.Context(), tx, id)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "event not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if !s.mayMutateEvent(c, existing, userID, canEditShared) {
			c.JSON(http.StatusForbidden, gin.H{"error": "not allowed to edit this event"})
			return errHandled
		}
		upd := &repository.CalendarEvent{
			Title: in.Title, Description: in.Description, Location: in.Location, FileID: in.FileID,
			StartAt: in.StartAt, EndAt: in.EndAt, AllDay: in.AllDay,
		}
		if err := repository.UpdateEventFields(c.Request.Context(), tx, id, existing.Scope, upd); err != nil {
			return err
		}
		// Regenerate future, unsent reminders against the new start time.
		if err := repository.DeleteFutureUnsentReminders(c.Request.Context(), tx, id); err != nil {
			return err
		}
		if err := generateReminders(c, tx, id, in.StartAt, in.Reminders); err != nil {
			return err
		}
		if err := repository.SetEventAttendees(c.Request.Context(), tx, id, in.AttendeeUserIDs); err != nil {
			return err
		}
		r, err := repository.RemindersForEvent(c.Request.Context(), tx, id)
		reminders = r
		return err
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true, "reminders": reminders})
	}
}

func (s *Server) DeleteCalendarEvent(c *gin.Context) {
	userID := s.claims(c).UserID()
	canDeleteShared := s.can(c, rbac.PermCalendarDeleteShared)
	id := c.Param("id")
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		existing, err := repository.GetEvent(c.Request.Context(), tx, id)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "event not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if !s.mayMutateEvent(c, existing, userID, canDeleteShared) {
			c.JSON(http.StatusForbidden, gin.H{"error": "not allowed to delete this event"})
			return errHandled
		}
		return repository.DeleteEventByID(c.Request.Context(), tx, id) // reminders cascade
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

// mayMutateEvent authorizes an edit/delete: personal events are owner-only (no
// permission, no role override — not even the Owner); shared events need the
// relevant calendar.*_shared permission (already resolved by the caller).
func (s *Server) mayMutateEvent(c *gin.Context, e *repository.CalendarEvent, userID string, sharedAllowed bool) bool {
	if e.Scope == "personal" {
		return e.OwnerID == userID
	}
	return sharedAllowed
}
