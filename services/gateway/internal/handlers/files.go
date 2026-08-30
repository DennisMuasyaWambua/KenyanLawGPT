package handlers

import (
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/repository"
)

func (s *Server) ListFiles(c *gin.Context) {
	var files []repository.File
	if s.withTenant(c, func(tx pgx.Tx) error {
		m, err := repository.ListFiles(c.Request.Context(), tx, c.Query("status"), c.Query("q"), c.Query("client_id"))
		files = m
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"files": files})
	}
}

type fileInput struct {
	Reference       string  `json:"reference" binding:"required"`
	Title           string  `json:"title" binding:"required"`
	Description     string  `json:"description"`
	ClientID        *string `json:"client_id"`
	Status          string  `json:"status"`
	PracticeArea    string  `json:"practice_area"`
	Court           string  `json:"court"`
	CourtCaseNumber string  `json:"court_case_number"`
	AssignedTo      *string `json:"assigned_to"`
	// NotifyClient (UpdateFile only): when a status change is saved, auto-send a
	// templated progress update to the consented client over email + SMS.
	NotifyClient bool `json:"notify_client"`
}

func (s *Server) CreateFile(c *gin.Context) {
	var in fileInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if in.Status == "" {
		in.Status = "intake"
	}
	m := &repository.File{
		ID: uuid.NewString(), Reference: in.Reference, Title: in.Title, Description: in.Description,
		ClientID: in.ClientID, Status: in.Status, PracticeArea: in.PracticeArea, Court: in.Court,
		CourtCaseNumber: in.CourtCaseNumber, AssignedTo: in.AssignedTo, CreatedBy: s.claims(c).UserID(),
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		// A file can only be opened once its client has been engaged (retainer
		// signed) — the onboarding pipeline gate.
		if m.ClientID != nil {
			cl, err := repository.ClientByID(c.Request.Context(), tx, *m.ClientID)
			if err == pgx.ErrNoRows {
				c.JSON(http.StatusBadRequest, gin.H{"error": "unknown client_id"})
				return errHandled
			}
			if err != nil {
				return err
			}
			if cl.Status != "engaged" && cl.Status != "active" {
				c.JSON(http.StatusUnprocessableEntity, gin.H{
					"error": "a file can only be opened for an engaged client (client is " + cl.Status + ")"})
				return errHandled
			}
		}
		if err := repository.InsertFile(c.Request.Context(), tx, m); err != nil {
			return err
		}
		return repository.InsertFileEvent(c.Request.Context(), tx, &repository.FileEvent{
			ID: uuid.NewString(), FileID: m.ID, EventType: "created", Note: "File opened", CreatedBy: m.CreatedBy,
		})
	}) {
		c.JSON(http.StatusCreated, gin.H{"file": m})
	}
}

func (s *Server) GetFile(c *gin.Context) {
	var file *repository.File
	var events []repository.FileEvent
	if s.withTenant(c, func(tx pgx.Tx) error {
		m, err := repository.FileByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		file = m
		events, err = repository.ListFileEvents(c.Request.Context(), tx, m.ID)
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"file": file, "events": events})
	}
}

func (s *Server) UpdateFile(c *gin.Context) {
	var in fileInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	var file *repository.File
	if s.withTenant(c, func(tx pgx.Tx) error {
		m, err := repository.FileByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		prevStatus := m.Status
		m.Title, m.Description, m.ClientID = in.Title, in.Description, in.ClientID
		if in.Status != "" {
			m.Status = in.Status
		}
		m.PracticeArea, m.Court, m.CourtCaseNumber, m.AssignedTo = in.PracticeArea, in.Court, in.CourtCaseNumber, in.AssignedTo
		if err := repository.UpdateFile(c.Request.Context(), tx, m); err != nil {
			return err
		}
		if prevStatus != m.Status {
			if err := repository.InsertFileEvent(c.Request.Context(), tx, &repository.FileEvent{
				ID: uuid.NewString(), FileID: m.ID, EventType: "status_change",
				Note: prevStatus + " -> " + m.Status, CreatedBy: s.claims(c).UserID(),
			}); err != nil {
				return err
			}
			// Automatic client update on status change (best-effort: a missing
			// client, no consent or a send failure must not fail the save).
			if in.NotifyClient {
				autoMsg := "The status of your matter is now: " + strings.ReplaceAll(m.Status, "_", " ") + "."
				_, _ = s.sendClientUpdate(c.Request.Context(), tx, m, autoMsg, []string{"email", "sms"}, s.claims(c).UserID())
			}
		}
		file = m
		return nil
	}) {
		c.JSON(http.StatusOK, gin.H{"file": file})
	}
}

func (s *Server) AddFileEvent(c *gin.Context) {
	var in struct {
		EventType string `json:"event_type" binding:"required"`
		Note      string `json:"note"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	e := &repository.FileEvent{
		ID: uuid.NewString(), FileID: c.Param("id"), EventType: in.EventType,
		Note: in.Note, CreatedBy: s.claims(c).UserID(),
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertFileEvent(c.Request.Context(), tx, e)
	}) {
		c.JSON(http.StatusCreated, gin.H{"event": e})
	}
}

func (s *Server) AddCourtDate(c *gin.Context) {
	var in struct {
		Date      time.Time `json:"date" binding:"required"`
		Courtroom string    `json:"courtroom"`
		Judge     string    `json:"judge"`
		Purpose   string    `json:"purpose"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	cd := &repository.CourtDate{
		ID: uuid.NewString(), FileID: c.Param("id"),
		Date: in.Date, Courtroom: in.Courtroom, Judge: in.Judge, Purpose: in.Purpose,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertCourtDate(c.Request.Context(), tx, cd)
	}) {
		c.JSON(http.StatusCreated, gin.H{"court_date": cd})
	}
}

func (s *Server) AddDeadline(c *gin.Context) {
	var in struct {
		Title    string     `json:"title" binding:"required"`
		DueAt    time.Time  `json:"due_at" binding:"required"`
		RemindAt *time.Time `json:"remind_at"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	remindAt := in.DueAt.Add(-24 * time.Hour)
	if in.RemindAt != nil {
		remindAt = *in.RemindAt
	}
	d := &repository.Deadline{
		ID: uuid.NewString(), FileID: c.Param("id"), Title: in.Title,
		DueAt: in.DueAt, RemindAt: remindAt, CreatedBy: s.claims(c).UserID(),
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertDeadline(c.Request.Context(), tx, d)
	}) {
		c.JSON(http.StatusCreated, gin.H{"deadline": d})
	}
}

// JudiciaryStatus looks up the live (or cached) court status for the file's
// case number through the pluggable adapter.
func (s *Server) JudiciaryStatus(c *gin.Context) {
	var caseNumber string
	if !s.withTenant(c, func(tx pgx.Tx) error {
		m, err := repository.FileByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		caseNumber = m.CourtCaseNumber
		return nil
	}) {
		return
	}
	if caseNumber == "" {
		badRequest(c, "file has no court case number")
		return
	}
	status, err := s.Judiciary.Lookup(c.Request.Context(), caseNumber)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "judiciary lookup failed", "detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": status})
}

// --- clients ---

func (s *Server) ListClients(c *gin.Context) {
	var clients []repository.Client
	if s.withTenant(c, func(tx pgx.Tx) error {
		cl, err := repository.ListClients(c.Request.Context(), tx, c.Query("status"))
		clients = cl
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"clients": clients})
	}
}

// GetClient returns one client with its onboarding stage history.
func (s *Server) GetClient(c *gin.Context) {
	var client *repository.Client
	var history []repository.StageEvent
	if s.withTenant(c, func(tx pgx.Tx) error {
		cl, err := repository.ClientByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		client = cl
		history, err = repository.ListStageEvents(c.Request.Context(), tx, cl.ID)
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"client": client, "stage_history": history})
	}
}

// CreateClient captures a new client at the "lead" stage (intake).
func (s *Server) CreateClient(c *gin.Context) {
	var in struct {
		Name             string `json:"name" binding:"required"`
		Email            string `json:"email"`
		Phone            string `json:"phone"`
		IDNumber         string `json:"id_number"`
		ClientType       string `json:"client_type"`
		CompanyRegNumber string `json:"company_reg_number"`
		KDPAConsent      bool   `json:"kdpa_consent"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	cl := &repository.Client{
		ID: uuid.NewString(), Name: in.Name, Email: in.Email, Phone: in.Phone,
		IDNumber: in.IDNumber, KDPAConsent: in.KDPAConsent, Status: "lead",
		ClientType: in.ClientType, CompanyRegNumber: in.CompanyRegNumber,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		if err := repository.InsertClient(c.Request.Context(), tx, cl); err != nil {
			return err
		}
		// Consent given at intake is logged for KDPA accountability.
		if in.KDPAConsent {
			return repository.InsertConsent(c.Request.Context(), tx, &repository.Consent{
				ID: uuid.NewString(), SubjectType: "client", SubjectID: cl.ID,
				Purpose: "client_intake_processing", Granted: true,
				GrantedBy: s.claims(c).UserID(), Source: "web",
			})
		}
		return nil
	}) {
		c.JSON(http.StatusCreated, gin.H{"client": cl})
	}
}

// Dashboard aggregates headline stats for the landing screen.
func (s *Server) Dashboard(c *gin.Context) {
	stats := gin.H{}
	if s.withTenant(c, func(tx pgx.Tx) error {
		row := tx.QueryRow(c.Request.Context(), `SELECT
			(SELECT count(*) FROM files WHERE status NOT IN ('closed')),
			(SELECT count(*) FROM files WHERE status = 'closed'),
			(SELECT count(*) FROM court_dates WHERE date BETWEEN now() AND now() + interval '7 days'),
			(SELECT count(*) FROM deadlines WHERE due_at BETWEEN now() AND now() + interval '7 days'),
			(SELECT COALESCE(sum(total_kes),0) FROM invoices WHERE status = 'sent'),
			(SELECT COALESCE(sum(total_kes),0) FROM invoices WHERE status = 'paid' AND paid_at > now() - interval '30 days'),
			(SELECT count(*) FROM archives),
			(SELECT count(*) FROM clients)`)
		var openFiles, closedFiles, courtDates, deadlines, docs, clients int64
		var outstanding, collected float64
		if err := row.Scan(&openFiles, &closedFiles, &courtDates, &deadlines, &outstanding, &collected, &docs, &clients); err != nil {
			return err
		}
		stats = gin.H{
			"open_files": openFiles, "closed_files": closedFiles,
			"court_dates_7d": courtDates, "deadlines_7d": deadlines,
			"outstanding_kes": outstanding, "collected_30d_kes": collected,
			"archives": docs, "clients": clients,
		}
		return nil
	}) {
		c.JSON(http.StatusOK, gin.H{"stats": stats})
	}
}
