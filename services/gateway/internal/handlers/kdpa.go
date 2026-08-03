package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	wakiliv1 "github.com/wakiliai/gateway/gen/wakiliv1"
	"github.com/wakiliai/gateway/internal/grpcclient"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/repository"
)

// Kenya Data Protection Act (2019) endpoints: consent logging, data-subject
// export (s.26/38), and right-to-erasure (s.40) cascading across Postgres,
// object storage, graph, and vectors.

func (s *Server) LogConsent(c *gin.Context) {
	var in struct {
		SubjectType string `json:"subject_type" binding:"required,oneof=client user"`
		SubjectID   string `json:"subject_id" binding:"required"`
		Purpose     string `json:"purpose" binding:"required"`
		Granted     bool   `json:"granted"`
		Source      string `json:"source"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if in.Source == "" {
		in.Source = "web"
	}
	consent := &repository.Consent{
		ID: uuid.NewString(), SubjectType: in.SubjectType, SubjectID: in.SubjectID,
		Purpose: in.Purpose, Granted: in.Granted, GrantedBy: s.claims(c).UserID(), Source: in.Source,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertConsent(c.Request.Context(), tx, consent)
	}) {
		c.JSON(http.StatusCreated, gin.H{"consent": consent})
	}
}

func (s *Server) ListConsents(c *gin.Context) {
	var consents []repository.Consent
	if s.withTenant(c, func(tx pgx.Tx) error {
		cl, err := repository.ListConsents(c.Request.Context(), tx, c.Query("subject_type"), c.Query("subject_id"))
		consents = cl
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"consents": consents})
	}
}

// ExportSubject returns every personal-data record held for a data subject —
// the KDPA subject-access / portability response.
func (s *Server) ExportSubject(c *gin.Context) {
	subjectType, subjectID := c.Query("subject_type"), c.Query("subject_id")
	if subjectType == "" || subjectID == "" {
		badRequest(c, "subject_type and subject_id are required")
		return
	}
	var export map[string]any
	if s.withTenant(c, func(tx pgx.Tx) error {
		e, err := repository.ExportSubject(c.Request.Context(), tx, subjectType, subjectID)
		export = e
		return err
	}) {
		c.Header("Content-Disposition", `attachment; filename="kdpa-export-`+subjectID+`.json"`)
		c.JSON(http.StatusOK, export)
	}
}

// EraseSubject is the right-to-erasure cascade:
//  1. collect the subject's documents (ids + object keys)
//  2. delete the objects from tenant-prefixed storage
//  3. gRPC EraseSubject -> AI service deletes tenant graph nodes + vectors
//  4. delete/anonymize Postgres rows
// Owner/partner only (enforced in the router).
func (s *Server) EraseSubject(c *gin.Context) {
	var in struct {
		SubjectType string `json:"subject_type" binding:"required,oneof=client user"`
		SubjectID   string `json:"subject_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	tenant := s.tenant(c)

	var docIDs, objectKeys []string
	if !s.withTenant(c, func(tx pgx.Tx) error {
		ids, keys, err := repository.DocumentIDsForSubject(c.Request.Context(), tx, in.SubjectType, in.SubjectID)
		docIDs, objectKeys = ids, keys
		return err
	}) {
		return
	}

	for _, key := range objectKeys {
		if err := s.Store.Delete(c.Request.Context(), tenant.ID, key); err != nil {
			logging.L(c.Request.Context()).Warn("erasure: object delete", "key", key, "err", err)
		}
	}

	graphNodes, vectorRows := int32(0), int32(0)
	ctx := grpcclient.Ctx(c.Request.Context(), tenant.ID, middleware.TraceID(c))
	report, err := s.AI.Ingestion.EraseSubject(ctx, &wakiliv1.EraseSubjectRequest{
		Tenant:      grpcclient.TC(tenant.ID, tenant.Plan, tenant.DataResidencyKE),
		SubjectType: in.SubjectType,
		SubjectId:   in.SubjectID,
		DocumentIds: docIDs,
	})
	if err != nil {
		logging.L(c.Request.Context()).Error("erasure: graph cascade failed", "err", err)
	} else {
		graphNodes, vectorRows = report.GraphNodesDeleted, report.VectorRowsDeleted
	}

	var rowsErased int64
	if s.withTenant(c, func(tx pgx.Tx) error {
		n, err := repository.EraseSubject(c.Request.Context(), tx, in.SubjectType, in.SubjectID)
		rowsErased = n
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{
			"erased": gin.H{
				"postgres_rows":   rowsErased,
				"storage_objects": len(objectKeys),
				"graph_nodes":     graphNodes,
				"vector_rows":     vectorRows,
			},
			"graph_cascade_ok": err == nil,
		})
	}
}

// AuditLog exposes the tenant's KDPA audit trail (owner/partner only).
func (s *Server) AuditLog(c *gin.Context) {
	tenant := s.tenant(c)
	var entries []repository.AuditEntry
	if s.withTenant(c, func(tx pgx.Tx) error {
		e, err := repository.ListAudit(c.Request.Context(), tx, tenant.ID, 200)
		entries = e
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"audit": entries})
	}
}
