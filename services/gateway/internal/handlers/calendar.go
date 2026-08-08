package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

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

func (s *Server) ListCalendarEvents(c *gin.Context) {
	from, ok := parseTime(c.Query("from"))
	if !ok {
		from = time.Now().AddDate(0, 0, -7)
	}
	to, ok := parseTime(c.Query("to"))
	if !ok {
		to = time.Now().AddDate(0, 0, 60)
	}
	userID := s.claims(c).UserID()
	var events []repository.CalendarEvent
	if s.withTenant(c, func(tx pgx.Tx) error {
		e, err := repository.ListEvents(c.Request.Context(), tx, userID, from, to)
		events = e
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"events": events})
	}
}

type eventInput struct {
	Scope       string     `json:"scope" binding:"required,oneof=personal firm"`
	Title       string     `json:"title" binding:"required"`
	Description string     `json:"description"`
	Location    string     `json:"location"`
	MatterID    *string    `json:"matter_id"`
	StartAt     time.Time  `json:"start_at" binding:"required"`
	EndAt       *time.Time `json:"end_at"`
	AllDay      bool       `json:"all_day"`
	RemindAt    *time.Time `json:"remind_at"`
}

func (s *Server) CreateCalendarEvent(c *gin.Context) {
	var in eventInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	userID := s.claims(c).UserID()
	e := &repository.CalendarEvent{
		ID: uuid.NewString(), Scope: in.Scope, Title: in.Title, Description: in.Description,
		Location: in.Location, MatterID: in.MatterID, OwnerID: userID, StartAt: in.StartAt,
		EndAt: in.EndAt, AllDay: in.AllDay, RemindAt: in.RemindAt, CreatedBy: userID,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.CreateEvent(c.Request.Context(), tx, e)
	}) {
		c.JSON(http.StatusCreated, gin.H{"event": e})
	}
}

func (s *Server) UpdateCalendarEvent(c *gin.Context) {
	var in eventInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	userID := s.claims(c).UserID()
	e := &repository.CalendarEvent{
		Title: in.Title, Description: in.Description, Location: in.Location, MatterID: in.MatterID,
		StartAt: in.StartAt, EndAt: in.EndAt, AllDay: in.AllDay, RemindAt: in.RemindAt,
	}
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		err := repository.UpdateEvent(c.Request.Context(), tx, c.Param("id"), userID, e)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusForbidden, gin.H{"error": "event not found or not editable by you"})
			return errHandled
		}
		return err
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

func (s *Server) DeleteCalendarEvent(c *gin.Context) {
	userID := s.claims(c).UserID()
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		err := repository.DeleteEvent(c.Request.Context(), tx, c.Param("id"), userID)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusForbidden, gin.H{"error": "event not found or not deletable by you"})
			return errHandled
		}
		return err
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}
