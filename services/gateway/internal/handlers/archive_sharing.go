package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/repository"
)

// GetArchiveVersions returns a document's version chain (newest first).
func (s *Server) GetArchiveVersions(c *gin.Context) {
	me, senior := s.claims(c).UserID(), s.isSenior(c)
	var versions []repository.Archive
	allowed := true
	if s.withTenant(c, func(tx pgx.Tx) error {
		ok, err := repository.CanAccessArchive(c.Request.Context(), tx, c.Param("id"), me, senior)
		if err != nil {
			return err
		}
		if !ok {
			allowed = false
			return nil
		}
		v, err := repository.ListArchiveVersions(c.Request.Context(), tx, c.Param("id"))
		versions = v
		return err
	}) {
		if !allowed {
			c.JSON(http.StatusForbidden, gin.H{"error": "you don't have access to this document"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"versions": versions})
	}
}

// GetArchiveShares returns the sharing state of a document plus the firm's
// members (so the UI can offer a share picker).
func (s *Server) GetArchiveShares(c *gin.Context) {
	me, senior := s.claims(c).UserID(), s.isSenior(c)
	var doc *repository.Archive
	var shares []string
	var users []repository.User
	allowed := true
	if s.withTenant(c, func(tx pgx.Tx) error {
		ok, err := repository.CanAccessArchive(c.Request.Context(), tx, c.Param("id"), me, senior)
		if err != nil {
			return err
		}
		if !ok {
			allowed = false
			return nil
		}
		doc, err = repository.ArchiveByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		shares, err = repository.ListArchiveShareUserIDs(c.Request.Context(), tx, doc.ID)
		if err != nil {
			return err
		}
		users, err = repository.ListUsers(c.Request.Context(), tx)
		return err
	}) {
		if !allowed {
			c.JSON(http.StatusForbidden, gin.H{"error": "you don't have access to this document"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"restricted": doc.Restricted, "shared_user_ids": shares, "users": users})
	}
}

// SetArchiveShares updates a document's restriction + share list. Only the
// uploader or the Managing Partner may change it.
func (s *Server) SetArchiveShares(c *gin.Context) {
	var in struct {
		Restricted bool     `json:"restricted"`
		UserIDs    []string `json:"user_ids"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	me, senior := s.claims(c).UserID(), s.isSenior(c)
	if s.withTenant(c, func(tx pgx.Tx) error {
		doc, err := repository.ArchiveByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		if doc.UploadedBy != me && !senior {
			c.JSON(http.StatusForbidden, gin.H{"error": "only the uploader or Managing Partner can change sharing"})
			return errHandled
		}
		if err := repository.SetArchiveRestricted(c.Request.Context(), tx, doc.ID, in.Restricted); err != nil {
			return err
		}
		return repository.ReplaceArchiveShares(c.Request.Context(), tx, doc.ID, in.UserIDs)
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}
