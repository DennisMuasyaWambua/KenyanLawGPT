package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	wakiliv1 "github.com/wakiliai/gateway/gen/wakiliv1"
	"github.com/wakiliai/gateway/internal/grpcclient"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/middleware"
	"github.com/wakiliai/gateway/internal/repository"
)

func provenanceJSON(p *wakiliv1.Provenance) gin.H {
	if p == nil {
		return nil
	}
	return gin.H{
		"source_type": p.SourceType.String(),
		"source_id":   p.SourceId,
		"citation":    p.Citation,
		"source_url":  p.SourceUrl,
		"status":      p.Status.String(),
		"court":       p.Court,
		"year":        p.Year,
	}
}

func chunksJSON(chunks []*wakiliv1.ContextChunk) []gin.H {
	out := make([]gin.H, 0, len(chunks))
	for _, ch := range chunks {
		out = append(out, gin.H{
			"chunk_id":   ch.ChunkId,
			"text":       ch.Text,
			"score":      ch.Score,
			"provenance": provenanceJSON(ch.Provenance),
			"metadata":   ch.Metadata,
		})
	}
	return out
}

// ResearchQuery runs the hybrid vector+graph retrieval and returns the
// synthesized answer with provenance-tagged citations.
func (s *Server) ResearchQuery(c *gin.Context) {
	var in struct {
		Query             string `json:"query" binding:"required"`
		MatterID          string `json:"matter_id"`
		TopK              int32  `json:"top_k"`
		IncludeSuperseded bool   `json:"include_superseded"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	tenant := s.tenant(c)
	ctx := grpcclient.Ctx(c.Request.Context(), tenant.ID, middleware.TraceID(c))
	resp, err := s.AI.Retrieval.Retrieve(ctx, &wakiliv1.TenantScopedQuery{
		Tenant:            grpcclient.TC(tenant.ID, tenant.Plan, tenant.DataResidencyKE),
		Query:             in.Query,
		TopK:              in.TopK,
		IncludeSuperseded: in.IncludeSuperseded,
		MatterId:          in.MatterID,
		TraceId:           middleware.TraceID(c),
	})
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "ai service unavailable", "detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"answer":  resp.Answer,
		"intent":  resp.ClassifiedIntent.String(),
		"chunks":  chunksJSON(resp.Chunks),
		"trace_id": resp.TraceId,
	})
}

// ResearchReason exposes the multi-hop graph reasoning trace.
func (s *Server) ResearchReason(c *gin.Context) {
	var in struct {
		Query             string `json:"query" binding:"required"`
		MatterID          string `json:"matter_id"`
		MaxHops           int32  `json:"max_hops"`
		IncludeSuperseded bool   `json:"include_superseded"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	tenant := s.tenant(c)
	ctx := grpcclient.Ctx(c.Request.Context(), tenant.ID, middleware.TraceID(c))
	resp, err := s.AI.Reasoning.Reason(ctx, &wakiliv1.ReasoningRequest{
		Tenant:            grpcclient.TC(tenant.ID, tenant.Plan, tenant.DataResidencyKE),
		Query:             in.Query,
		MaxHops:           in.MaxHops,
		MatterId:          in.MatterID,
		IncludeSuperseded: in.IncludeSuperseded,
		TraceId:           middleware.TraceID(c),
	})
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "ai service unavailable", "detail": err.Error()})
		return
	}
	steps := make([]gin.H, 0, len(resp.Steps))
	for _, st := range resp.Steps {
		steps = append(steps, gin.H{
			"hop": st.Hop, "description": st.Description,
			"node_ids": st.NodeIds, "edge_types": st.EdgeTypes,
		})
	}
	c.JSON(http.StatusOK, gin.H{
		"answer": resp.Answer, "steps": steps, "context": chunksJSON(resp.Context), "trace_id": resp.TraceId,
	})
}

var draftDocTypes = map[string]wakiliv1.DraftDocType{
	"pleading":       wakiliv1.DraftDocType_DRAFT_DOC_TYPE_PLEADING,
	"affidavit":      wakiliv1.DraftDocType_DRAFT_DOC_TYPE_AFFIDAVIT,
	"contract":       wakiliv1.DraftDocType_DRAFT_DOC_TYPE_CONTRACT,
	"correspondence": wakiliv1.DraftDocType_DRAFT_DOC_TYPE_CORRESPONDENCE,
	"demand_letter":  wakiliv1.DraftDocType_DRAFT_DOC_TYPE_DEMAND_LETTER,
}

// DraftStream is the end-to-end streaming path: Next.js fetch-stream ->
// this SSE endpoint -> gRPC server-stream -> Python -> LLM tokens.
func (s *Server) DraftStream(c *gin.Context) {
	var in struct {
		DocType      string `json:"doc_type" binding:"required"`
		Title        string `json:"title"`
		Instructions string `json:"instructions" binding:"required"`
		MatterID     string `json:"matter_id"`
		TemplateID   string `json:"template_id"`
		ContextQuery string `json:"context_query"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	docType, ok := draftDocTypes[strings.ToLower(in.DocType)]
	if !ok {
		badRequest(c, "doc_type must be one of pleading|affidavit|contract|correspondence|demand_letter")
		return
	}
	tenant := s.tenant(c)
	userID := s.claims(c).UserID()

	ctx := grpcclient.Ctx(c.Request.Context(), tenant.ID, middleware.TraceID(c))
	stream, err := s.AI.Drafting.DraftDocument(ctx, &wakiliv1.DraftRequest{
		Tenant:       grpcclient.TC(tenant.ID, tenant.Plan, tenant.DataResidencyKE),
		DocType:      docType,
		Instructions: in.Instructions,
		MatterId:     in.MatterID,
		TemplateId:   in.TemplateID,
		ContextQuery: in.ContextQuery,
		TraceId:      middleware.TraceID(c),
	})
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "ai service unavailable", "detail": err.Error()})
		return
	}

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	flusher, _ := c.Writer.(http.Flusher)

	sse := func(event string, payload any) {
		buf, err := json.Marshal(payload)
		if err != nil {
			return
		}
		if event != "" {
			fmt.Fprintf(c.Writer, "event: %s\n", event)
		}
		fmt.Fprintf(c.Writer, "data: %s\n\n", buf)
		if flusher != nil {
			flusher.Flush()
		}
	}

	var full strings.Builder
	var citations []*wakiliv1.Provenance
	for {
		chunk, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			logging.L(c.Request.Context()).Error("draft stream", "err", err)
			sse("error", gin.H{"error": "stream interrupted"})
			return
		}
		if chunk.Text != "" {
			full.WriteString(chunk.Text)
			sse("", gin.H{"text": chunk.Text})
		}
		if chunk.IsFinal {
			citations = chunk.Citations
		}
	}

	// Persist the completed draft with its provenance-tagged citations.
	draftID := uuid.NewString()
	citJSON := make([]gin.H, 0, len(citations))
	for _, p := range citations {
		citJSON = append(citJSON, provenanceJSON(p))
	}
	citBuf, _ := json.Marshal(citJSON)
	title := in.Title
	if title == "" {
		label := strings.ReplaceAll(strings.ToLower(in.DocType), "_", " ")
		title = strings.ToUpper(label[:1]) + label[1:] + " draft"
	}
	var matterID *string
	if in.MatterID != "" {
		matterID = &in.MatterID
	}
	if err := s.DB.WithTenant(c.Request.Context(), tenant.ID, tenant.SchemaName, func(tx pgx.Tx) error {
		return repository.InsertDraft(c.Request.Context(), tx, &repository.Draft{
			ID: draftID, MatterID: matterID, DocType: strings.ToLower(in.DocType),
			Title: title, Content: full.String(), Citations: citBuf, CreatedBy: userID,
		})
	}); err != nil {
		logging.L(c.Request.Context()).Error("persist draft", "err", err)
	}
	sse("done", gin.H{"draft_id": draftID, "citations": citJSON})
}
