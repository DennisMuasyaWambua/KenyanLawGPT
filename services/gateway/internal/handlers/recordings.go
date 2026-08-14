package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/storage"
)

// CreateRecording enforces the hard consent gate: no recording row is created
// unless the advocate has explicitly confirmed consent. Returns a presigned PUT
// URL for the browser to upload the audio straight to R2.
func (s *Server) CreateRecording(c *gin.Context) {
	var in struct {
		MatterID         *string `json:"matter_id"`
		ClientID         *string `json:"client_id"`
		Filename         string  `json:"filename" binding:"required"`
		MimeType         string  `json:"mime_type"`
		ConsentConfirmed bool    `json:"consent_confirmed"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if !in.ConsentConfirmed {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "consent must be confirmed before recording"})
		return
	}
	tenant := s.tenant(c)
	id := uuid.NewString()
	key := storage.Key(tenant.ID, id, in.Filename)
	uploadURL, err := s.Store.PresignPut(c.Request.Context(), tenant.ID, key)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "could not presign upload"})
		return
	}
	r := &repository.Recording{
		ID: id, MatterID: in.MatterID, AdvocateUserID: s.claims(c).UserID(), ClientID: in.ClientID,
		ObjectKey: key, Filename: in.Filename, MimeType: in.MimeType, ConsentConfirmed: true, Status: "recording",
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertRecording(c.Request.Context(), tx, r)
	}) {
		c.JSON(http.StatusCreated, gin.H{"recording": r, "upload_url": uploadURL})
	}
}

// MarkRecordingUploaded flips a recording to "transcribing" after the browser
// finishes the R2 upload; the AI background worker takes it from there.
func (s *Server) MarkRecordingUploaded(c *gin.Context) {
	var in struct {
		DurationSeconds int `json:"duration_seconds"`
	}
	_ = c.ShouldBindJSON(&in)
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		err := repository.MarkUploaded(c.Request.Context(), tx, c.Param("id"), s.claims(c).UserID(), in.DurationSeconds)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusForbidden, gin.H{"error": "recording not found or not yours"})
			return errHandled
		}
		return err
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true, "status": "transcribing"})
	}
}

// ListRecordings returns the caller's own recordings, or all firm recordings
// with recordings.view_all (and ?scope=all).
func (s *Server) ListRecordings(c *gin.Context) {
	wantAll := c.Query("scope") == "all" && s.can(c, rbac.PermRecordingsViewAll)
	var recs []repository.Recording
	if s.withTenant(c, func(tx pgx.Tx) error {
		var err error
		if wantAll {
			recs, err = repository.ListAllRecordings(c.Request.Context(), tx)
		} else {
			recs, err = repository.ListOwnRecordings(c.Request.Context(), tx, s.claims(c).UserID())
		}
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"recordings": recs})
	}
}

func (s *Server) GetRecording(c *gin.Context) {
	var rec *repository.Recording
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		r, err := repository.GetRecording(c.Request.Context(), tx, c.Param("id"))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "recording not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		// view_own callers may only see their own recordings.
		if r.AdvocateUserID != s.claims(c).UserID() && !s.can(c, rbac.PermRecordingsViewAll) {
			c.JSON(http.StatusForbidden, gin.H{"error": "not allowed to view this recording"})
			return errHandled
		}
		rec = r
		return nil
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"recording": rec})
	}
}

func (s *Server) MatterRecordings(c *gin.Context) {
	var recs []repository.Recording
	if s.withTenant(c, func(tx pgx.Tx) error {
		r, err := repository.ListRecordingsByMatter(c.Request.Context(), tx, c.Param("id"))
		recs = r
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"recordings": recs})
	}
}
