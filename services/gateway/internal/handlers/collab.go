package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/repository"
)

// Collaborative-document metadata + sharing. The real-time Yjs sync itself is
// handled by the separate collab WebSocket service; the gateway owns the
// document list, titles and the share list (access control).

func (s *Server) ListCollabDocs(c *gin.Context) {
	var docs []repository.CollabDocument
	if s.withTenant(c, func(tx pgx.Tx) error {
		d, err := repository.ListCollabDocuments(c.Request.Context(), tx, s.claims(c).UserID(), s.isSenior(c))
		docs = d
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"documents": docs})
	}
}

func (s *Server) CreateCollabDoc(c *gin.Context) {
	var in struct {
		Title  string  `json:"title"`
		FileID *string `json:"file_id"`
	}
	_ = c.ShouldBindJSON(&in)
	if in.Title == "" {
		in.Title = "Untitled document"
	}
	id := uuid.NewString()
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertCollabDocument(c.Request.Context(), tx, id, in.Title, s.claims(c).UserID(), in.FileID)
	}) {
		c.JSON(http.StatusCreated, gin.H{"id": id, "title": in.Title})
	}
}

func (s *Server) GetCollabDoc(c *gin.Context) {
	me, senior := s.claims(c).UserID(), s.isSenior(c)
	var doc *repository.CollabDocument
	var shares []string
	var users []repository.User
	allowed := true
	if s.withTenant(c, func(tx pgx.Tx) error {
		ok, err := repository.CanAccessCollab(c.Request.Context(), tx, c.Param("id"), me, senior)
		if err != nil {
			return err
		}
		if !ok {
			allowed = false
			return nil
		}
		doc, err = repository.GetCollabDocument(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		shares, err = repository.CollabShareUserIDs(c.Request.Context(), tx, doc.ID)
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
		c.JSON(http.StatusOK, gin.H{
			"document": doc, "shared_user_ids": shares, "users": users,
			"is_owner": doc.OwnerID == me || senior,
		})
	}
}

func (s *Server) RenameCollabDoc(c *gin.Context) {
	var in struct {
		Title string `json:"title" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	me, senior := s.claims(c).UserID(), s.isSenior(c)
	if s.withTenant(c, func(tx pgx.Tx) error {
		ok, err := repository.CanAccessCollab(c.Request.Context(), tx, c.Param("id"), me, senior)
		if err != nil {
			return err
		}
		if !ok {
			c.JSON(http.StatusForbidden, gin.H{"error": "no access"})
			return errHandled
		}
		return repository.RenameCollabDocument(c.Request.Context(), tx, c.Param("id"), in.Title)
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

func (s *Server) SetCollabShares(c *gin.Context) {
	var in struct {
		UserIDs []string `json:"user_ids"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	me, senior := s.claims(c).UserID(), s.isSenior(c)
	if s.withTenant(c, func(tx pgx.Tx) error {
		doc, err := repository.GetCollabDocument(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		if doc.OwnerID != me && !senior {
			c.JSON(http.StatusForbidden, gin.H{"error": "only the owner or Managing Partner can share"})
			return errHandled
		}
		return repository.ReplaceCollabShares(c.Request.Context(), tx, doc.ID, in.UserIDs)
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}
