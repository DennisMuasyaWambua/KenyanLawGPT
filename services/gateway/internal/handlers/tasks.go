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

type taskInput struct {
	FileID    string     `json:"file_id"`
	AssignedTo  *string    `json:"assigned_to"`
	Title       string     `json:"title"`
	Description string     `json:"description"`
	DueDate     *time.Time `json:"due_date"`
	Status      string     `json:"status"`
	Priority    string     `json:"priority"`
}

// CreateTask (tasks.create). Assigning to anyone other than yourself also
// requires tasks.assign; otherwise the task is self-assigned.
func (s *Server) CreateTask(c *gin.Context) {
	var in taskInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if in.FileID == "" || in.Title == "" {
		badRequest(c, "file_id and title are required")
		return
	}
	self := s.claims(c).UserID()
	assignee := self
	if in.AssignedTo != nil && *in.AssignedTo != "" {
		assignee = *in.AssignedTo
	}
	if assignee != self && !s.can(c, rbac.PermTasksAssign) {
		c.JSON(http.StatusForbidden, gin.H{"error": "missing permission: " + rbac.PermTasksAssign})
		return
	}
	if in.Status == "" {
		in.Status = "todo"
	}
	if in.Priority == "" {
		in.Priority = "medium"
	}
	t := &repository.Task{
		ID: uuid.NewString(), FileID: in.FileID, AssignedTo: &assignee, AssignedBy: self,
		Title: in.Title, Description: in.Description, DueDate: in.DueDate, Status: in.Status, Priority: in.Priority,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertTask(c.Request.Context(), tx, t)
	}) {
		c.JSON(http.StatusCreated, gin.H{"task": t})
	}
}

// UpdateTask: a task manager (tasks.create) may edit everything; the assignee
// may always update the status of their own task even without tasks.create.
func (s *Server) UpdateTask(c *gin.Context) {
	var in taskInput
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	self := s.claims(c).UserID()
	canManage := s.can(c, rbac.PermTasksCreate)
	canAssign := s.can(c, rbac.PermTasksAssign)
	id := c.Param("id")
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		existing, err := repository.GetTask(c.Request.Context(), tx, id)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "task not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if canManage {
			assignee := existing.AssignedTo
			if in.AssignedTo != nil {
				assignee = in.AssignedTo
			}
			// Reassigning to a different person needs tasks.assign.
			reassigning := (assignee == nil) != (existing.AssignedTo == nil) ||
				(assignee != nil && existing.AssignedTo != nil && *assignee != *existing.AssignedTo)
			if reassigning && assignee != nil && *assignee != self && !canAssign {
				c.JSON(http.StatusForbidden, gin.H{"error": "missing permission: " + rbac.PermTasksAssign})
				return errHandled
			}
			existing.AssignedTo = assignee
			if in.Title != "" {
				existing.Title = in.Title
			}
			existing.Description = in.Description
			existing.DueDate = in.DueDate
			if in.Status != "" {
				existing.Status = in.Status
			}
			if in.Priority != "" {
				existing.Priority = in.Priority
			}
			return repository.UpdateTaskFull(c.Request.Context(), tx, existing)
		}
		// Not a manager: only the assignee may change status.
		if existing.AssignedTo == nil || *existing.AssignedTo != self {
			c.JSON(http.StatusForbidden, gin.H{"error": "you can only update the status of tasks assigned to you"})
			return errHandled
		}
		if in.Status == "" {
			badRequest(c, "status is required")
			return errHandled
		}
		return repository.UpdateTaskStatus(c.Request.Context(), tx, id, in.Status)
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

func (s *Server) DeleteTask(c *gin.Context) {
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.DeleteTask(c.Request.Context(), tx, c.Param("id"))
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

// ListTasks returns the caller's own tasks, or all firm tasks when they hold
// tasks.view_all (and pass ?scope=all).
func (s *Server) ListTasks(c *gin.Context) {
	wantAll := c.Query("scope") == "all" && s.can(c, rbac.PermTasksViewAll)
	var tasks []repository.Task
	if s.withTenant(c, func(tx pgx.Tx) error {
		var err error
		if wantAll {
			tasks, err = repository.ListAllTasks(c.Request.Context(), tx)
		} else {
			tasks, err = repository.ListOwnTasks(c.Request.Context(), tx, s.claims(c).UserID())
		}
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"tasks": tasks, "scope": map[bool]string{true: "all", false: "own"}[wantAll]})
	}
}

func (s *Server) FileTasks(c *gin.Context) {
	var tasks []repository.Task
	if s.withTenant(c, func(tx pgx.Tx) error {
		t, err := repository.ListTasksByFile(c.Request.Context(), tx, c.Param("id"))
		tasks = t
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"tasks": tasks})
	}
}

// CaseDashboard (files.view_all): per-file open/overdue task counts, last
// activity and current status.
func (s *Server) CaseDashboard(c *gin.Context) {
	var cases []repository.CaseStatus
	if s.withTenant(c, func(tx pgx.Tx) error {
		cs, err := repository.CaseDashboard(c.Request.Context(), tx)
		cases = cs
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"cases": cases})
	}
}
