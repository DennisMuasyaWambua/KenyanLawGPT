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
	if s.withTenant(c, func(tx pgx.Tx) error {
		cs, err := repository.ListArchiveComments(c.Request.Context(), tx, archiveID)
		comments = cs
		return err
	}) {
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
		return repository.InsertArchiveComment(c.Request.Context(), tx, cm)
	}) {
		c.JSON(http.StatusCreated, gin.H{"comment": cm})
	}
}
