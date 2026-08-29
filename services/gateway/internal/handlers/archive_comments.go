package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/repository"
)

// ListArchiveComments returns the collaboration thread on a document.
func (s *Server) ListArchiveComments(c *gin.Context) {
	archiveID := c.Param("id")
	var comments []repository.ArchiveComment
	allowed := true
	if s.withTenant(c, func(tx pgx.Tx) error {
		ok, err := repository.CanAccessArchive(c.Request.Context(), tx, archiveID, s.claims(c).UserID(), s.isSenior(c))
		if err != nil {
			return err
		}
		if !ok {
			allowed = false
			return nil
		}
		cs, err := repository.ListArchiveComments(c.Request.Context(), tx, archiveID)
		comments = cs
		return err
	}) {
		if !allowed {
			c.JSON(http.StatusForbidden, gin.H{"error": "you don't have access to this document"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"comments": comments})
	}
}

// AddArchiveComment posts a comment on a document.
func (s *Server) AddArchiveComment(c *gin.Context) {
	archiveID := c.Param("id")
	var in struct {
		Body string `json:"body" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	cm := &repository.ArchiveComment{
		ID: uuid.NewString(), ArchiveID: archiveID, UserID: s.claims(c).UserID(), Body: in.Body,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		ok, err := repository.CanAccessArchive(c.Request.Context(), tx, archiveID, s.claims(c).UserID(), s.isSenior(c))
		if err != nil {
			return err
		}
		if !ok {
			c.JSON(http.StatusForbidden, gin.H{"error": "you don't have access to this document"})
			return errHandled
		}
		return repository.InsertArchiveComment(c.Request.Context(), tx, cm)
	}) {
		c.JSON(http.StatusCreated, gin.H{"comment": cm})
	}
}
