package handlers

import (
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	wakiliv1 "github.com/wakiliai/gateway/gen/wakiliv1"
	"github.com/wakiliai/gateway/internal/grpcclient"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/storage"
)

// PresignUpload creates the document row and hands the browser a short-lived
// PUT URL scoped to the tenant's object prefix. The gateway is the only
// issuer of signed URLs — the AI service and frontend never hold S3 creds.
func (s *Server) PresignUpload(c *gin.Context) {
	var in struct {
		Filename string  `json:"filename" binding:"required"`
		MimeType string  `json:"mime_type"`
		SizeB    int64   `json:"size_bytes"`
		MatterID *string `json:"matter_id"`
		DocKind  string  `json:"doc_kind"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if in.DocKind == "" {
		in.DocKind = "other"
	}
	tenant := s.tenant(c)
	docID := uuid.NewString()
	key := storage.Key(tenant.ID, docID, in.Filename)
	uploadURL, err := s.Store.PresignPut(c.Request.Context(), tenant.ID, key)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "presign failed"})
		return
	}
	doc := &repository.Document{
		ID: docID, MatterID: in.MatterID, Filename: in.Filename, ObjectKey: key,
		MimeType: in.MimeType, SizeBytes: in.SizeB, DocKind: in.DocKind,
		UploadedBy: s.claims(c).UserID(), IngestStatus: "pending",
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertDocument(c.Request.Context(), tx, doc)
	}) {
		c.JSON(http.StatusCreated, gin.H{"document": doc, "upload_url": uploadURL})
	}
}

// IngestDocument triggers the Python AI service's tenant-private ingestion
// over the mTLS gRPC stream and relays the staged progress.
func (s *Server) IngestDocument(c *gin.Context) {
	tenant := s.tenant(c)
	var doc *repository.Document
	if !s.withTenant(c, func(tx pgx.Tx) error {
		d, err := repository.DocumentByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		doc = d
		return repository.SetIngestStatus(c.Request.Context(), tx, d.ID, "ingesting")
	}) {
		return
	}

	ctx := grpcclient.Ctx(c.Request.Context(), tenant.ID, middleware.TraceID(c))
	stream, err := s.AI.Ingestion.IngestDocument(ctx, &wakiliv1.IngestRequest{
		Tenant:     grpcclient.TC(tenant.ID, tenant.Plan, tenant.DataResidencyKE),
		DocumentId: doc.ID,
		ObjectKey:  doc.ObjectKey,
		Filename:   doc.Filename,
		MimeType:   doc.MimeType,
		MatterId:   deref(doc.MatterID),
		TraceId:    middleware.TraceID(c),
	})
	if err != nil {
		s.markIngest(c, doc.ID, "failed")
		c.JSON(http.StatusBadGateway, gin.H{"error": "ai service unavailable", "detail": err.Error()})
		return
	}

	var stages []gin.H
	finalStatus := "ingested"
	for {
		st, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			logging.L(c.Request.Context()).Error("ingest stream", "err", err)
			finalStatus = "failed"
			break
		}
		stages = append(stages, gin.H{
			"stage": st.Stage.String(), "message": st.Message, "progress": st.ProgressPct,
		})
		if st.Stage == wakiliv1.IngestStage_INGEST_STAGE_FAILED {
			finalStatus = "failed"
		}
	}
	s.markIngest(c, doc.ID, finalStatus)
	c.JSON(http.StatusOK, gin.H{"document_id": doc.ID, "ingest_status": finalStatus, "stages": stages})
}

func (s *Server) markIngest(c *gin.Context, docID, status string) {
	tenant := s.tenant(c)
	_ = s.DB.WithTenant(c.Request.Context(), tenant.ID, tenant.SchemaName, func(tx pgx.Tx) error {
		return repository.SetIngestStatus(c.Request.Context(), tx, docID, status)
	})
}

func (s *Server) ListDocuments(c *gin.Context) {
	var docs []repository.Document
	if s.withTenant(c, func(tx pgx.Tx) error {
		d, err := repository.ListDocuments(c.Request.Context(), tx, c.Query("matter_id"))
		docs = d
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"documents": docs})
	}
}

func (s *Server) DownloadDocument(c *gin.Context) {
	tenant := s.tenant(c)
	var doc *repository.Document
	if !s.withTenant(c, func(tx pgx.Tx) error {
		d, err := repository.DocumentByID(c.Request.Context(), tx, c.Param("id"))
		doc = d
		return err
	}) {
		return
	}
	url, err := s.Store.PresignGet(c.Request.Context(), tenant.ID, doc.ObjectKey)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "presign failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"download_url": url, "filename": doc.Filename})
}

func (s *Server) ListDrafts(c *gin.Context) {
	var drafts []repository.Draft
	if s.withTenant(c, func(tx pgx.Tx) error {
		d, err := repository.ListDrafts(c.Request.Context(), tx, c.Query("matter_id"))
		drafts = d
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"drafts": drafts})
	}
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
